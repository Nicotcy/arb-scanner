#!/usr/bin/env python3
"""CLI entry point for arb-scanner."""

from __future__ import annotations

import argparse
import os
import sys

from arb_scanner.config import load_config
from arb_scanner.scanner import compute_opportunities, format_opportunity_table, summarize_config
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only scanner for Kalshi/Polymarket")
    parser.add_argument(
        "--use-stub",
        action="store_true",
        help="Use stub data instead of live APIs (default in this repo).",
    )
    parser.add_argument(
        "--use-kalshi",
        action="store_true",
        help="Use Kalshi public data and run the scanner pipeline.",
    )
    parser.add_argument(
        "--kalshi-market-prices",
        action="store_true",
        help="Print Kalshi market ask prices from list_open_markets.",
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
    elif args.kalshi_market_prices:
        from arb_scanner.kalshi_public import KalshiPublicClient

        client = KalshiPublicClient()
        markets = list(client.list_open_markets(max_pages=1))
        printed = 0
        for market in markets:
            if printed >= 50:
                break
            ticker = market.get("ticker")
            if not ticker or ticker.startswith("KXMVE") or "MULTIGAMEEXTENDED" in ticker:
                continue
            yes_ask = market.get("yes_ask")
            no_ask = market.get("no_ask")
            if not yes_ask or not no_ask:
                continue
            yes_ask_prob = yes_ask / 100.0
            no_ask_prob = no_ask / 100.0
            spread_sum = yes_ask_prob + no_ask_prob
            print(f"{ticker}")
            print(f"  yes_ask={yes_ask_prob}")
            print(f"  no_ask={no_ask_prob}")
            print(f"  spread_sum={spread_sum}")
            printed += 1
        return 0
    elif args.use_kalshi:
        provider = KalshiProvider()
        limit = int(os.getenv("KALSHI_SNAPSHOT_N", "20"))
        print("KALSHI SNAPSHOTS (read-only)")
        snapshots = list(provider.fetch_market_snapshots())
        print(f"snapshots={len(snapshots)}")
        for snapshot in snapshots[:limit]:
            yes_ask = snapshot.orderbook.best_yes_price
            no_ask = snapshot.orderbook.best_no_price
            yes_bid = None
            no_bid = None
            qty_yes = snapshot.orderbook.best_yes_size
            qty_no = snapshot.orderbook.best_no_size
            liquidity = (
                min(qty_yes or 0, qty_no or 0)
                if qty_yes and qty_no
                else (qty_yes or qty_no or 0)
            )
            spread_sum = (yes_ask or 0) + (no_ask or 0)
            ticker = snapshot.market.market_id
            print(
                f"{ticker} | "
                f"yes_ask={yes_ask} no_ask={no_ask} "
                f"yes_bid={yes_bid} no_bid={no_bid} "
                f"qtyY={qty_yes} qtyN={qty_no} "
                f"liquidity={liquidity} "
                f"spread_sum={spread_sum}"
            )
        return 0
    else:
        from arb_scanner.kalshi_public import KalshiPublicClient

        print("KALSHI LIVE DEMO (read-only)")
        demo_count = int(os.getenv("KALSHI_DEMO_N", "10"))
        max_scan = int(os.getenv("KALSHI_DEMO_MAX_SCAN", "200"))
        client = KalshiPublicClient()
        debug_ticker = os.getenv("KALSHI_DEBUG_ONE_TICKER")
        if debug_ticker:
            client.fetch_top_of_book(debug_ticker)
            sys.exit(0)
        max_pages = int(os.getenv("KALSHI_DEMO_MAX_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_DEMO_LIMIT", "200"))
        markets = list(
            client.list_open_markets(
                max_pages=max_pages, limit_per_page=limit_per_page
            )
        )
        blacklist_prefixes = ("KXMVESPORTS",)
        blacklist_substrings = ("MULTIGAMEEXTENDED",)
        markets = [
            market
            for market in markets
            if not any(
                (market.get("ticker") or "").startswith(prefix)
                for prefix in blacklist_prefixes
            )
            and not any(
                substring in (market.get("ticker") or "")
                for substring in blacklist_substrings
            )
        ]
        activity_key = None
        for key in ("volume_24h", "volume", "open_interest"):
            active_markets = [
                market
                for market in markets
                if (market.get(key) or 0) > 0
            ]
            if active_markets:
                activity_key = key
                markets = sorted(
                    active_markets,
                    key=lambda market: market.get(key) or 0,
                    reverse=True,
                )
                break
        print(f"after_filter_markets={len(markets)}")
        tickers = [market.get("ticker") for market in markets if market.get("ticker")]
        print(
            "demo_count="
            f"{demo_count} "
            "max_scan="
            f"{max_scan} "
            "pages="
            f"{max_pages} "
            "limit="
            f"{limit_per_page} "
            "tickers="
            f"{len(tickers)}"
        )
        printed = 0
        scanned = 0
        for ticker in tickers:
            if scanned >= max_scan or printed >= demo_count:
                break
            scanned += 1
            if scanned % 5 == 0:
                print(f"scanned={scanned} printed={printed}")
            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                continue
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
