from __future__ import annotations

import argparse
import os
import sys

from arb_scanner.config import load_config
from arb_scanner.scanner import compute_opportunities, format_opportunity_table, summarize_config
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--use-stub", action="store_true", help="Use stub providers.")
    parser.add_argument("--use-kalshi", action="store_true", help="Use Kalshi read-only snapshots.")

    parser.add_argument(
        "--kalshi-market-prices",
        action="store_true",
        help="Print sample Kalshi market prices using expanded leg tickers + top-of-book.",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()

    # Mantener DRY_RUN encendido por seguridad
    if not config.dry_run:
        raise SystemExit("DRY_RUN must remain enabled for this scanner.")

    if args.use_stub:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")
        snapshots_a = list(provider_a.fetch_market_snapshots())
        snapshots_b = list(provider_b.fetch_market_snapshots())

    elif args.kalshi_market_prices:
        from arb_scanner.kalshi_public import KalshiPublicClient

        client = KalshiPublicClient()

        max_pages = int(os.getenv("KALSHI_PAGES", "3"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        tickers_to_price: list[str] = []
        seen: set[str] = set()

        for market in client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page):
            t = market.get("ticker")
            if not t:
                continue

            legs = market.get("mve_selected_legs") or []
            if legs:
                for leg in legs:
                    lt = leg.get("market_ticker")
                    if lt and lt not in seen:
                        tickers_to_price.append(lt)
                        seen.add(lt)
            else:
                if t not in seen:
                    tickers_to_price.append(t)
                    seen.add(t)

        printed = 0
        for ticker in tickers_to_price:
            if printed >= 50:
                break
            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                continue
            if top.yes_ask is None or top.no_ask is None:
                continue

            yes_ask_prob = top.yes_ask / 100.0
            no_ask_prob = top.no_ask / 100.0
            spread_sum = yes_ask_prob + no_ask_prob

            print(f"{ticker}")
            print(f"  yes_ask={yes_ask_prob}")
            print(f"  no_ask={no_ask_prob}")
            print(f"  spread_sum={spread_sum}")
            printed += 1

        return 0

    elif args.use_kalshi:
        from arb_scanner.sources.kalshi import KalshiProvider

        provider = KalshiProvider()
        snapshots_a = list(provider.fetch_market_snapshots())
        snapshots_b = []  # todavía no metemos Polymarket aquí

    else:
        raise SystemExit("Choose one: --use-stub, --use-kalshi, or --kalshi-market-prices")

    # Si solo tenemos Kalshi, no habrá oportunidades cross-venue todavía
    if not snapshots_b:
        print(summarize_config(config))
        print("No opportunities found.")
        return 0

    opps = compute_opportunities(snapshots_a, snapshots_b, config)
    print(summarize_config(config))
    if opps:
        print(format_opportunity_table(opps))
    else:
        print("No opportunities found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
