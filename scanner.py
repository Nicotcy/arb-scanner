#!/usr/bin/env python3
"""CLI entry point for arb-scanner."""

from __future__ import annotations

import argparse
import os
import sys

from arb_scanner.config import load_config
from arb_scanner.scanner import compute_opportunities, format_opportunity_table, summarize_config
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only scanner for Kalshi/Polymarket")
    parser.add_argument(
        "--use-stub",
        action="store_true",
        help="Use stub data instead of live APIs (default in this repo).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    if not config.dry_run:
        raise SystemExit("DRY_RUN must remain enabled for this scanner.")

    if args.use_stub:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")
    else:
        from arb_scanner.kalshi_public import KalshiPublicClient

        print("KALSHI LIVE DEMO (read-only)")
        demo_count = int(os.getenv("KALSHI_DEMO_N", "10"))
        max_scan = int(os.getenv("KALSHI_DEMO_MAX_SCAN", "200"))
        max_scan = int(os.getenv("KALSHI_DEMO_MAX_SCAN", "500"))
        client = KalshiPublicClient()
        markets = list(client.list_open_markets(max_pages=1))
        activity_key = None
        for key in ("volume_24h", "volume", "open_interest"):
            if any(key in market for market in markets):
                activity_key = key
                active_markets = [
                    market for market in markets if (market.get(key) or 0) > 0
                ]
                if active_markets:
                    markets = sorted(
                        active_markets,
                        key=lambda market: market.get(key) or 0,
                        reverse=True,
                    )
                break
        tickers = [market.get("ticker") for market in markets if market.get("ticker")]
        printed = 0
        scanned = 0
        for ticker in tickers:
            if scanned >= max_scan or printed >= demo_count:
                break
            scanned += 1
            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                continue
            top = client.fetch_top_of_book(ticker)
            if (
                (top.yes_bid is None and top.no_bid is None)
                or (top.yes_ask is None and top.no_ask is None)
            ):
                continue
            print(
                f"{top.ticker} | "
                f"yes_bid={top.yes_bid} yes_ask={top.yes_ask} "
                f"no_bid={top.no_bid} no_ask={top.no_ask} "
                f"qtyY={top.yes_bid_qty} qtyN={top.no_bid_qty}"
            )
            printed += 1
        if scanned >= max_scan and printed == 0:
            print(
                "No usable markets found in first "
                f"{max_scan} open markets (no bids)."
            )
        print(f"Printed {printed} usable markets (scanned {scanned}).")
        sys.exit(0)

    markets_a = list(provider_a.fetch_market_snapshots())
    markets_b = list(provider_b.fetch_market_snapshots())
    opportunities = compute_opportunities(markets_a, markets_b, config)

    if config.alert_only:
        opportunities = [
            opportunity
            for opportunity in opportunities
            if opportunity.net_edge >= config.alert_threshold
        ]

    print(f"Scanner config: {summarize_config(config)}")
    if not opportunities:
        print("No opportunities found.")
        return 0

    print(format_opportunity_table(opportunities))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
