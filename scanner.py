#!/usr/bin/env python3
"""CLI entry point for arb-scanner."""

from __future__ import annotations

import argparse

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
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")

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
