from __future__ import annotations

import argparse
import json
import os
import random
import time
import traceback
import uuid

import requests

from arb_scanner.config import apply_mode, load_config
from arb_scanner.kalshi_public import KalshiPublicClient
from arb_scanner.mappings import load_manual_mappings, MarketMapping
from arb_scanner.polymarket_public import PolymarketPublicClient
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.polymarket import PolymarketProvider
from arb_scanner.storage import SnapshotRow, Storage


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="arb-scanner daemon loop (read-only, persistent, 24/7 style)")

    p.add_argument("--mode", choices=["lab", "safe"], default=os.getenv("MODE", "lab"))
    p.add_argument("--use-kalshi", action="store_true", help="Scan Kalshi internal (batches over whole universe).")
    p.add_argument("--use-mapping", action="store_true", help="Scan cross-venue using manual mappings (Kalshi<->Poly).")

    p.add_argument(
        "--refresh-markets-secs",
        type=int,
        default=int(os.getenv("REFRESH_MARKETS_SECS", "600")),
        help="How often to refresh the full list of open Kalshi markets.",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("BATCH_SIZE", "300")),
        help="How many Kalshi tickers to scan per loop iteration.",
    )
    p.add_argument(
        "--sleep-secs",
        type=float,
        default=float(os.getenv("SLEEP_SECS", "2.0")),
        help="Sleep between iterations (controls request pressure).",
    )

    p.add_argument(
        "--state-path",
        default=os.getenv("DAEMON_STATE_PATH", ".state/kalshi_cursor.json"),
        help="Where to persist cursor across restarts.",
    )
    p.add_argument(
        "--db-path",
        default=os.getenv("DB_PATH", ".data/scan.db"),
        help="SQLite path for snapshots + signals.",
    )

    p.add_argument("--internal-floor", type=float, default=float(os.getenv("INTERNAL_FLOOR", "-0.02")))
    p.add_argument("--internal-ceiling", type=float, default=float(os.getenv("INTERNAL_CEILING", "0.02")))
    p.add_argument("--alert-threshold", type=float, default=float(os.getenv("ALERT_THRESHOLD", "0.02")))

    return p.parse_args()


class Backoff:
    def __init__(self, base: float = 30.0, factor: float = 2.0, cap: float = 600.0, jitter: float = 0.20):
        self.base = float(base)
        self.factor = float(factor)
        self.cap = float(cap)
        self.jitter = float(jitter)
        self.attempt = 0

    def reset(self) -> None:
        self.attempt = 0

    def next_sleep(self) -> float:
        delay = min(self.cap, self.base * (self.factor ** self.attempt))
        self.attempt += 1
        if self.jitter > 0:
            wiggle = delay * self.jitter
            delay = max(0.0, delay + random.uniform(-wiggle, +wiggle))
        return delay


def load_cursor(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("cursor", 0))
    except Exception:
        return 0


def save_cursor(path: str, cursor: int) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cursor": int(cursor), "ts": int(time.time())}, f, indent=2)


def fee_buffer(cost: float, fee_buffer_bps: float) -> float:
    return cost * (fee_buffer_bps / 10_000.0)


def iter_batches(items: list[str], start: int, batch_size: int) -> tuple[list[str], int]:
    n = len(items)
    if n == 0:
        return [], 0
    start = start % n
    end = start + batch_size
    if end <= n:
        batch = items[start:end]
    else:
        batch = items[start:] + items[: end % n]
    new_cursor = (start + batch_size) % n
    return batch, new_cursor


def resolve_polymarket_tokens(mappings: list[MarketMapping]) -> list[MarketMapping]:
    client = PolymarketPublicClient()
    out: list[MarketMapping] = []
    for mp in mappings:
        if mp.polymarket_yes_token_id and mp.polymarket_no_token_id:
            out.append(mp)
            continue
        resolved = client.resolve_slug_to_yes_no_token_ids(mp.polymarket_slug)
        if not resolved:
            out.append(mp)
            continue
        yes_id, no_id = resolved
        out.append(
            MarketMapping(
                kalshi_ticker=mp.kalshi_ticker,
                polymarket_slug=mp.polymarket_slug,
                polymarket_yes_token_id=yes_id,
                polymarket_no_token_id=no_id,
            )
        )
    return out


def _is_networkish(e: Exception) -> bool:
    if isinstance(e, requests.RequestException):
        return True
    if isinstance(e, OSError):
        return True
    return False


def main() -> int:
    args = parse_args()

    config = apply_mode(load_config(), args.mode)
    if not config.dry_run:
        raise SystemExit("DRY_RUN must remain enabled (daemon is read-only).")

    if not args.use_kalshi and not args.use_mapping:
        raise SystemExit("Choose at least one: --use-kalshi and/or --use-mapping")

    run_id = str(uuid.uuid4())
    store = Storage(args.db_path)
    store.start_run(run_id, config.mode, notes=f"use_kalshi={args.use_kalshi} use_mapping={args.use_mapping}")

    backoff = Backoff(
        base=float(os.getenv("NET_BACKOFF_BASE", "30")),
        cap=float(os.getenv("NET_BACKOFF_CAP", "600")),
    )

    kalshi_client = KalshiPublicClient()
    last_refresh = 0
    kalshi_universe: list[str] = []
    cursor = load_cursor(args.state_path)

    resolved_mappings: list[MarketMapping] = []
    if args.use_mapping:
        mappings = load_manual_mappings()
        if not mappings:
            raise SystemExit("No mappings defined in arb_scanner/mappings.py")
        resolved = resolve_polymarket_tokens(mappings)
        unresolved = [m for m in resolved if not (m.polymarket_yes_token_id and m.polymarket_no_token_id)]
        if unresolved:
            print("Some mappings could not be resolved (Gamma). Fix these slugs:")
            for m in unresolved:
                print(f"  - {m.polymarket_slug} (kalshi={m.kalshi_ticker})")
            raise SystemExit(2)
        resolved_mappings = resolved

    print(f"[daemon] run_id={run_id} mode={config.mode} db={args.db_path}")

    while True:
        try:
            now = int(time.time())

            if args.use_kalshi and (now - last_refresh >= args.refresh_markets_secs or not kalshi_universe):
                try:
                    markets = list(
                        kalshi_client.list_open_markets(
                            max_pages=int(os.getenv("KALSHI_PAGES", "200")),
                            limit_per_page=int(os.getenv("KALSHI_LIMIT", "200")),
                        )
                    )
                    kalshi_universe = [m.get("ticker") for m in markets if m.get("ticker")]
                    kalshi_universe.sort()
                    last_refresh = now
                    print(f"[daemon] refreshed kalshi universe: {len(kalshi_universe)} tickers")
                except Exception as e:
                    if kalshi_universe:
                        last_refresh = now
                        tag = "net" if _is_networkish(e) else "err"
                        print(
                            f"[daemon] WARN[{tag}] kalshi universe refresh failed; using cached universe "
                            f"(n={len(kalshi_universe)}): {type(e).__name__}: {e}"
                        )
                    else:
                        raise

            if args.use_kalshi and kalshi_universe:
                batch, cursor = iter_batches(kalshi_universe, cursor, args.batch_size)
                save_cursor(args.state_path, cursor)

                try:
                    provider = KalshiProvider(include_tickers=set(batch))
                except TypeError:
                    provider = KalshiProvider()

                snapshots = list(provider.fetch_market_snapshots())
                ts = int(time.time())

                rows: list[SnapshotRow] = []
                for s in snapshots:
                    rows.append(
                        SnapshotRow(
                            ts=ts,
                            venue=s.market.venue,
                            market_id=s.market.market_id,
                            question=s.market.question,
                            yes_ask=s.orderbook.best_yes_price,
                            no_ask=s.orderbook.best_no_price,
                            yes_sz=float(s.orderbook.best_yes_size or 0.0),
                            no_sz=float(s.orderbook.best_no_size or 0.0),
                            raw=None,
                        )
                    )
                store.insert_snapshots(rows)

                for s in snapshots:
                    ya = s.orderbook.best_yes_price
                    na = s.orderbook.best_no_price
                    if ya is None or na is None:
                        continue
                    cost = float(ya) + float(na)
                    raw_edge = 1.0 - cost
                    buf_edge = raw_edge - fee_buffer(cost, config.fee_buffer_bps)
                    exe = min(float(s.orderbook.best_yes_size or 0.0), float(s.orderbook.best_no_size or 0.0))

                    if args.internal_floor <= buf_edge <= args.internal_ceiling:
                        store.insert_signal(
                            ts=ts,
                            kind="kalshi_internal",
                            a_venue="Kalshi",
                            a_market_id=s.market.market_id,
                            b_venue=None,
                            b_market_id=None,
                            sum_price=cost,
                            raw_edge=raw_edge,
                            buf_edge=buf_edge,
                            exec_size=exe,
                            details=f"question={s.market.question}",
                        )

                print(
                    f"[daemon] kalshi batch={len(batch)} snapshots={len(snapshots)} "
                    f"cursor={cursor}/{len(kalshi_universe)}"
                )

            if args.use_mapping and resolved_mappings:
                k_tickers = {m.kalshi_ticker for m in resolved_mappings}
                provider_k = KalshiProvider(include_tickers=set(k_tickers))
                snaps_k = list(provider_k.fetch_market_snapshots())

                provider_p = PolymarketProvider(mappings=resolved_mappings)
                snaps_p = list(provider_p.fetch_market_snapshots())

                ts = int(time.time())
                rows = []
                for s in snaps_k + snaps_p:
                    rows.append(
                        SnapshotRow(
                            ts=ts,
                            venue=s.market.venue,
                            market_id=s.market.market_id,
                            question=s.market.question,
                            yes_ask=s.orderbook.best_yes_price,
                            no_ask=s.orderbook.best_no_price,
                            yes_sz=float(s.orderbook.best_yes_size or 0.0),
                            no_sz=float(s.orderbook.best_no_size or 0.0),
                            raw=None,
                        )
                    )
                store.insert_snapshots(rows)

                index_k = {s.market.market_id: s for s in snaps_k}
                index_p = {s.market.market_id: s for s in snaps_p}

                for mp in resolved_mappings:
                    ks = index_k.get(mp.kalshi_ticker)
                    ps = index_p.get(mp.polymarket_slug) or index_p.get(f"Poly:{mp.polymarket_slug}")
                    if not ks or not ps:
                        continue

                    k_yes = ks.orderbook.best_yes_price
                    p_no = ps.orderbook.best_no_price
                    if k_yes is not None and p_no is not None:
                        cost = float(k_yes) + float(p_no)
                        raw_edge = 1.0 - cost
                        buf_edge = raw_edge - fee_buffer(cost, config.fee_buffer_bps)
                        exe = min(float(ks.orderbook.best_yes_size or 0.0), float(ps.orderbook.best_no_size or 0.0))
                        if buf_edge >= args.alert_threshold and exe >= config.min_executable_size:
                            store.insert_signal(
                                ts=ts,
                                kind="cross_venue",
                                a_venue="Kalshi",
                                a_market_id=mp.kalshi_ticker,
                                b_venue="Polymarket",
                                b_market_id=mp.polymarket_slug,
                                sum_price=cost,
                                raw_edge=raw_edge,
                                buf_edge=buf_edge,
                                exec_size=exe,
                                details="BUY yes@kalshi + no@poly",
                            )
                            print(
                                f"[ALERT] cross_venue {mp.kalshi_ticker} <-> {mp.polymarket_slug} "
                                f"buf_edge={buf_edge:.4f} exe={exe:.2f}"
                            )

                    p_yes = ps.orderbook.best_yes_price
                    k_no = ks.orderbook.best_no_price
                    if p_yes is not None and k_no is not None:
                        cost = float(p_yes) + float(k_no)
                        raw_edge = 1.0 - cost
                        buf_edge = raw_edge - fee_buffer(cost, config.fee_buffer_bps)
                        exe = min(float(ps.orderbook.best_yes_size or 0.0), float(ks.orderbook.best_no_size or 0.0))
                        if buf_edge >= args.alert_threshold and exe >= config.min_executable_size:
                            store.insert_signal(
                                ts=ts,
                                kind="cross_venue",
                                a_venue="Polymarket",
                                a_market_id=mp.polymarket_slug,
                                b_venue="Kalshi",
                                b_market_id=mp.kalshi_ticker,
                                sum_price=cost,
                                raw_edge=raw_edge,
                                buf_edge=buf_edge,
                                exec_size=exe,
                                details="BUY yes@poly + no@kalshi",
                            )
                            print(
                                f"[ALERT] cross_venue {mp.polymarket_slug} <-> {mp.kalshi_ticker} "
                                f"buf_edge={buf_edge:.4f} exe={exe:.2f}"
                            )

                print(f"[daemon] mapping tickers={len(resolved_mappings)}")

            backoff.reset()
            time.sleep(args.sleep_secs)

        except KeyboardInterrupt:
            print("\n[daemon] KeyboardInterrupt: exiting cleanly.")
            break

        except Exception as e:
            tag = "net" if _is_networkish(e) else "err"
            print(f"[daemon] ERROR[{tag}]: {type(e).__name__}: {e}")
            traceback.print_exc()

            s = backoff.next_sleep()
            print(f"[daemon] backoff sleeping {s:.1f}s then retry...")
            time.sleep(s)
            continue

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
