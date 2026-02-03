from __future__ import annotations

import os
import sqlite3
import time
import json
from dataclasses import dataclass
from typing import Iterable, Any


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  started_at INTEGER NOT NULL,
  mode TEXT NOT NULL,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
  ts INTEGER NOT NULL,
  venue TEXT NOT NULL,
  market_id TEXT NOT NULL,
  question TEXT,
  yes_ask REAL,
  no_ask REAL,
  yes_sz REAL,
  no_sz REAL,
  raw JSON,
  PRIMARY KEY (ts, venue, market_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_market ON snapshots(venue, market_id, ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON snapshots(ts);

CREATE TABLE IF NOT EXISTS signals (
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,            -- 'kalshi_internal' | 'cross_venue'
  a_venue TEXT,
  a_market_id TEXT,
  b_venue TEXT,
  b_market_id TEXT,
  sum_price REAL,
  raw_edge REAL,
  buf_edge REAL,
  exec_size REAL,
  details TEXT
);

CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);

-- Paper trading state + logs (no real trading)
CREATE TABLE IF NOT EXISTS paper_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_trades (
  trade_id TEXT PRIMARY KEY,
  ts_open INTEGER NOT NULL,
  ts_close INTEGER,
  status TEXT NOT NULL,          -- 'open' | 'closed' | 'canceled'
  kind TEXT NOT NULL,            -- 'cross_venue'
  size REAL NOT NULL,
  sum_price REAL NOT NULL,
  buf_edge REAL NOT NULL,
  expected_profit REAL NOT NULL,
  legs_json TEXT NOT NULL,       -- JSON with legs
  details TEXT
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_open ON paper_trades(status, ts_open);

CREATE TABLE IF NOT EXISTS paper_orders (
  order_id TEXT PRIMARY KEY,
  trade_id TEXT,
  ts INTEGER NOT NULL,
  venue TEXT NOT NULL,
  market_id TEXT NOT NULL,
  side TEXT NOT NULL,            -- 'YES' | 'NO'
  action TEXT NOT NULL,          -- 'BUY' | 'SELL'
  price REAL NOT NULL,
  size REAL NOT NULL,
  status TEXT NOT NULL,          -- 'filled' | 'rejected' | 'canceled'
  filled_size REAL NOT NULL,
  details TEXT
);

CREATE INDEX IF NOT EXISTS idx_paper_orders_ts ON paper_orders(ts);
"""


@dataclass(frozen=True)
class SnapshotRow:
    ts: int
    venue: str
    market_id: str
    question: str | None
    yes_ask: float | None
    no_ask: float | None
    yes_sz: float | None
    no_sz: float | None
    raw: str | None


class Storage:
    """
    SQLite storage tuned for long-running daemons.

    Features:
      - WAL mode
      - INSERT OR IGNORE snapshots (idempotent by PK)
      - TTL pruning for snapshots (keep last N days)
      - optional WAL checkpoint to avoid giant -wal files
      - paper-trading tables for safe simulation

    Env tuning (optional):
      - SQLITE_BUSY_TIMEOUT_MS (default 5000)
    """

    def __init__(self, path: str) -> None:
        d = os.path.dirname(path) or "."
        os.makedirs(d, exist_ok=True)

        self.path = path
        self.conn = sqlite3.connect(path, timeout=5.0)
        busy_ms = int(os.getenv("SQLITE_BUSY_TIMEOUT_MS", "5000"))
        self.conn.execute(f"PRAGMA busy_timeout = {busy_ms};")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.commit()
        finally:
            self.conn.close()

    def start_run(self, run_id: str, mode: str, notes: str = "") -> None:
        now = int(time.time())
        self.conn.execute(
            "INSERT OR REPLACE INTO runs(run_id, started_at, mode, notes) VALUES(?,?,?,?)",
            (run_id, now, mode, notes),
        )
        self.conn.commit()

    def insert_snapshots(self, rows: Iterable[SnapshotRow]) -> int:
        cur = self.conn.cursor()
        n = 0
        for r in rows:
            cur.execute(
                """
                INSERT OR IGNORE INTO snapshots(ts, venue, market_id, question, yes_ask, no_ask, yes_sz, no_sz, raw)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (r.ts, r.venue, r.market_id, r.question, r.yes_ask, r.no_ask, r.yes_sz, r.no_sz, r.raw),
            )
            n += cur.rowcount
        self.conn.commit()
        return n

    def insert_signal(
        self,
        *,
        ts: int,
        kind: str,
        a_venue: str | None,
        a_market_id: str | None,
        b_venue: str | None,
        b_market_id: str | None,
        sum_price: float | None,
        raw_edge: float | None,
        buf_edge: float | None,
        exec_size: float | None,
        details: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO signals(ts, kind, a_venue, a_market_id, b_venue, b_market_id,
                                sum_price, raw_edge, buf_edge, exec_size, details)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ts,
                kind,
                a_venue,
                a_market_id,
                b_venue,
                b_market_id,
                sum_price,
                raw_edge,
                buf_edge,
                exec_size,
                details,
            ),
        )
        self.conn.commit()

    def prune_snapshots(self, *, keep_days: int) -> int:
        """
        Delete old snapshots outside retention window.

        Returns number of deleted rows.
        """
        keep_days = int(keep_days)
        if keep_days <= 0:
            return 0

        cutoff = int(time.time()) - keep_days * 86400
        cur = self.conn.cursor()
        cur.execute("DELETE FROM snapshots WHERE ts < ?", (cutoff,))
        deleted = cur.rowcount
        self.conn.commit()
        return deleted

    def wal_checkpoint(self, mode: str = "TRUNCATE") -> None:
        """
        Help keep the -wal file under control. Safe to call occasionally.

        mode: PASSIVE | FULL | RESTART | TRUNCATE
        """
        mode = (mode or "TRUNCATE").upper()
        if mode not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
            mode = "TRUNCATE"
        try:
            self.conn.execute(f"PRAGMA wal_checkpoint({mode});")
            self.conn.commit()
        except Exception:
            pass

    # -------------------------
    # Paper trading helpers
    # -------------------------

    def paper_get(self, key: str, default: Any = None) -> Any:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM paper_state WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return default

    def paper_set(self, key: str, value: Any) -> None:
        payload = json.dumps(value)
        self.conn.execute(
            "INSERT OR REPLACE INTO paper_state(key, value) VALUES(?, ?)",
            (key, payload),
        )
        self.conn.commit()

    def paper_insert_trade(
        self,
        *,
        trade_id: str,
        ts_open: int,
        kind: str,
        size: float,
        sum_price: float,
        buf_edge: float,
        expected_profit: float,
        legs: dict,
        status: str = "open",
        details: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO paper_trades(
                trade_id, ts_open, ts_close, status, kind, size, sum_price, buf_edge, expected_profit, legs_json, details
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                trade_id,
                ts_open,
                None,
                status,
                kind,
                float(size),
                float(sum_price),
                float(buf_edge),
                float(expected_profit),
                json.dumps(legs),
                details,
            ),
        )
        self.conn.commit()

    def paper_close_trade(self, trade_id: str, ts_close: int, status: str = "closed") -> None:
        self.conn.execute(
            "UPDATE paper_trades SET ts_close = ?, status = ? WHERE trade_id = ?",
            (int(ts_close), status, trade_id),
        )
        self.conn.commit()

    def paper_insert_order(
        self,
        *,
        order_id: str,
        trade_id: str,
        ts: int,
        venue: str,
        market_id: str,
        side: str,
        action: str,
        price: float,
        size: float,
        status: str,
        filled_size: float,
        details: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO paper_orders(
                order_id, trade_id, ts, venue, market_id, side, action, price, size, status, filled_size, details
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                order_id,
                trade_id,
                int(ts),
                venue,
                market_id,
                side,
                action,
                float(price),
                float(size),
                status,
                float(filled_size),
                details,
            ),
        )
        self.conn.commit()

    def paper_list_open_trades(self, limit: int = 1000) -> list[tuple[str, int, float, float, float]]:
        """
        Returns (trade_id, ts_open, size, sum_price, expected_profit)
        """
        cur = self.conn.cursor()
        cur.execute(
            "SELECT trade_id, ts_open, size, sum_price, expected_profit FROM paper_trades WHERE status='open' ORDER BY ts_open ASC LIMIT ?",
            (int(limit),),
        )
        return cur.fetchall()
