from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass

from arb_scanner.storage import Storage


@dataclass(frozen=True)
class PaperConfig:
    settle_after_secs: int = 3600  # auto-close paper trades after 1h (simulates resolution/closeout)
    fee_bps: float = 0.0          # rough fee model; buffer is handled elsewhere
    min_free_balance: float = 0.0 # keep a floor of free balance


@dataclass(frozen=True)
class Leg:
    venue: str
    market_id: str
    side: str   # 'YES' | 'NO'
    action: str # 'BUY'
    price: float
    size_avail: float


@dataclass(frozen=True)
class TradePlan:
    kind: str               # 'cross_venue'
    buf_edge: float
    sum_price: float
    size: float
    legs: tuple[Leg, Leg]
    details: str = ""


class PaperExecutor:
    """A minimal paper-trading executor.

    This does NOT place real orders. It simply:
      - checks that both legs have enough top-of-book size
      - checks bankroll / free balance constraints
      - logs a paper trade + paper orders in SQLite
      - tracks free/locked balances in paper_state
      - auto-settles open trades after `settle_after_secs`
    """

    def __init__(self, store: Storage, *, cfg: PaperConfig | None = None) -> None:
        self.store = store
        self.cfg = cfg or PaperConfig()

        # Initialize paper balances if absent.
        if self.store.paper_get("free_balance") is None:
            bankroll = float(os.getenv("PAPER_BANKROLL", "1000"))
            self.store.paper_set("free_balance", bankroll)
            self.store.paper_set("locked_balance", 0.0)
            self.store.paper_set("realized_pnl", 0.0)

    def balances(self) -> tuple[float, float, float]:
        free = float(self.store.paper_get("free_balance", 0.0))
        locked = float(self.store.paper_get("locked_balance", 0.0))
        pnl = float(self.store.paper_get("realized_pnl", 0.0))
        return free, locked, pnl

    def _set_balances(self, free: float, locked: float, pnl: float) -> None:
        self.store.paper_set("free_balance", float(free))
        self.store.paper_set("locked_balance", float(locked))
        self.store.paper_set("realized_pnl", float(pnl))

    def try_execute(self, plan: TradePlan) -> tuple[bool, str]:
        """Attempt a paper execution. Returns (ok, reason)."""
        now = int(time.time())
        free, locked, pnl = self.balances()

        # Validate legs have enough liquidity at top-of-book
        for leg in plan.legs:
            if leg.size_avail < plan.size:
                return False, f"insufficient_liquidity {leg.venue}:{leg.market_id} {leg.side} avail={leg.size_avail:.4f} need={plan.size:.4f}"

        # Capital model (simple): you pay sum_price * size now, then you lock it until settlement.
        cost = plan.sum_price * plan.size
        if free - cost < self.cfg.min_free_balance:
            return False, f"insufficient_balance free={free:.2f} cost={cost:.2f} floor={self.cfg.min_free_balance:.2f}"

        trade_id = str(uuid.uuid4())

        # Log orders (filled instantly at best ask)
        for leg in plan.legs:
            oid = str(uuid.uuid4())
            self.store.paper_insert_order(
                order_id=oid,
                trade_id=trade_id,
                ts=now,
                venue=leg.venue,
                market_id=leg.market_id,
                side=leg.side,
                action=leg.action,
                price=leg.price,
                size=plan.size,
                status="filled",
                filled_size=plan.size,
                details="paper fill at top-of-book",
            )

        # Log trade (open)
        expected_profit = (1.0 - plan.sum_price) * plan.size  # ignores fees; buf_edge already accounts for your buffer
        legs_json = {
            "legs": [
                {"venue": l.venue, "market_id": l.market_id, "side": l.side, "action": l.action, "price": l.price, "size": plan.size}
                for l in plan.legs
            ]
        }
        self.store.paper_insert_trade(
            trade_id=trade_id,
            ts_open=now,
            kind=plan.kind,
            size=plan.size,
            sum_price=plan.sum_price,
            buf_edge=plan.buf_edge,
            expected_profit=expected_profit,
            legs=legs_json,
            status="open",
            details=plan.details,
        )

        # Move balance: free -> locked
        free -= cost
        locked += cost
        self._set_balances(free, locked, pnl)

        return True, f"executed trade_id={trade_id} cost={cost:.2f} expected_profit={expected_profit:.2f}"

    def maybe_settle(self) -> int:
        """Auto-close open trades after a time window and realize expected profit."""
        now = int(time.time())
        open_trades = self.store.paper_list_open_trades(limit=10000)
        if not open_trades:
            return 0

        free, locked, pnl = self.balances()
        n_closed = 0

        for trade_id, ts_open, size, sum_price, expected_profit in open_trades:
            if now - int(ts_open) < int(self.cfg.settle_after_secs):
                continue

            # Unlock capital and realize expected profit.
            cost = float(sum_price) * float(size)
            locked = max(0.0, locked - cost)
            free += cost
            free += float(expected_profit)
            pnl += float(expected_profit)

            self.store.paper_close_trade(trade_id, ts_close=now, status="closed")
            n_closed += 1

        if n_closed:
            self._set_balances(free, locked, pnl)

        return n_closed
