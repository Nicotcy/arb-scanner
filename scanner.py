#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from arb_scanner.config import load_config
from arb_scanner.scanner import format_opportunity_table, summarize_config, run_scan
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prediction market arbitrage scanner (dry-run).")

    p.add_argument("--use-stub", action="store_true", help="Use stub providers (no network).")
    p.add_argument("--use-kalshi", action="store_true", help="Use Kalshi provider vs Stub.")
    p.add_argument(
        "--kalshi-market-prices",
        action="store_true",
        help="Debug: print Kalshi market ask prices from market listing (expands MVEs).",
    )

    p.add_argument(
        "--min-edge",
        type=float,
        default=float(os.getenv("MIN_EDGE", "0.0")),
        help="Minimum edge to report (e.g. 0.01 = 1%%).",
    )

    return p.parse_args()


def cmd_kalshi_market_prices() -> int:
    from arb_scanner.kalshi_public import KalshiPublicClient

    max_pages = int(os.getenv("KALSHI_PAGES", "3"))
    limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))
    max_print = int(os.getenv("KALSHI_PRINT", "50"))

    client = KalshiPublicClient()
    markets = list(client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page))

    tickers: list[str] = []
    seen: set[str] = set()

    for m in markets:
        t = m.get("ticker")
        if not t:
            continue
        if t.startswith("KXMVE") or "MULTIGAMEEXTENDED" in t:
            for leg in (m.get("mve_selected_legs") or []):
                lt = leg.get("market_ticker")
                if lt and lt not in seen:
                    tickers.append(lt)
                    seen.add(lt)
            continue
        if t not in seen:
            tickers.append(t)
            seen.add(t)

    by_ticker = {m.get("ticker"): m for m in markets if m.get("ticker")}

    printed = 0
    for t in tickers:
        if printed >= max_print:
            break
        m = by_ticker.get(t)
        if not m:
            continue
        yes_ask = m.get("yes_ask")
        no_ask = m.get("no_ask")
        if yes_ask is None or no_ask is None:
            continue

        yes_p = float(yes_ask) / 100.0
        no_p = float(no_ask) / 100.0
        spread_sum = yes_p + no_p

        print(t)
        print(f"  yes_ask={yes_p}")
        print(f"  no_ask={no_p}")
        print(f"  spread_sum={spread_sum}")
        printed += 1

    return 0


def main() -> int:
    args = parse_args()
    config = load_config()

    if not config.dry_run:
        raise SystemExit("DRY_RUN must remain enabled for this scanner.")

    if args.kalshi_market_prices:
        return cmd_kalshi_market_prices()

    if args.use_stub:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")
    elif args.use_kalshi:
        provider_a = KalshiProvider()
        provider_b = StubProvider("Polymarket")
    else:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")

    print(summarize_config(config))
    opps = run_scan(provider_a, provider_b, min_edge=args.min_edge)
    print(format_opportunity_table(opps, limit=25))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
