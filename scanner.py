from __future__ import annotations

import argparse
import os

from arb_scanner.config import load_config
from arb_scanner.mappings import load_manual_mappings
from arb_scanner.scanner import (
    compute_opportunities,
    format_near_miss_pairs_table,
    format_opportunity_table,
    summarize_config,
)
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.polymarket_stub import PolymarketStubProvider
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument("--use-stub", action="store_true", help="Use stub providers.")
    parser.add_argument("--use-kalshi", action="store_true", help="Use Kalshi read-only snapshots.")
    parser.add_argument(
        "--use-mapping",
        action="store_true",
        help="Use manual Kalshi<->Polymarket mappings (Polymarket stub for now).",
    )
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

    snapshots_a = []
    snapshots_b = []

    if args.use_stub:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")
        snapshots_a = list(provider_a.fetch_market_snapshots())
        snapshots_b = list(provider_b.fetch_market_snapshots())

    elif args.use_mapping:
        # 1) Kalshi snapshots
        provider_a = KalshiProvider()
        snapshots_a = list(provider_a.fetch_market_snapshots())

        # 2) Polymarket stub (por ahora vacío)
        provider_b = PolymarketStubProvider()
        snapshots_b = list(provider_b.fetch_market_snapshots())

        # 3) Mappings manuales (todavía no los usamos para fetch real porque Polymarket es stub)
        mappings = load_manual_mappings()
        if not mappings:
            print(summarize_config(config))
            print("No manual mappings defined yet. Add mappings in arb_scanner/mappings.py")
            return 0

        print(summarize_config(config))
        print(f"Loaded {len(mappings)} manual mappings. (Polymarket is stub for now)")
        # Seguimos para imprimir near-miss de Kalshi (y luego cross cuando Polymarket sea real)

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
        provider = KalshiProvider()
        snapshots_a = list(provider.fetch_market_snapshots())
        snapshots_b = []  # todavía no metemos Polymarket aquí

    else:
        raise SystemExit("Choose one: --use-stub, --use-kalshi, --use-mapping, or --kalshi-market-prices")

    # Oportunidades (si hay dos venues); si no, lista vacía
    opportunities = []
    if snapshots_b:
        opportunities = compute_opportunities(snapshots_a, snapshots_b, config)

    print(summarize_config(config))

    if opportunities:
        print(format_opportunity_table(opportunities))
    else:
        print("No opportunities found.")

    near_miss_pairs = format_near_miss_pairs_table(snapshots_a, snapshots_b, config)
    if near_miss_pairs:
        print("Near-miss opportunities (top 20):")
        print(near_miss_pairs)
    else:
        print("No valid binary markets for near-miss table.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
