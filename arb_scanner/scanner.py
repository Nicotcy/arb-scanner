from __future__ import annotations

import argparse

from arb_scanner.scanner import run_scan
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arbitrage scanner (dry-run)")
    parser.add_argument("--use-stub", action="store_true", help="Run using stub data")
    parser.add_argument(
        "--use-kalshi",
        action="store_true",
        help="Fetch Kalshi snapshots (read-only) and print count",
    )
    parser.add_argument(
        "--kalshi-market-prices",
        action="store_true",
        help="Print Kalshi market ask prices from list_open_markets (expands MVE legs).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # El scanner está diseñado como dry-run por defecto
    # (si en tu repo existe config/DRY_RUN esto se valida dentro de run_scan)
    if args.use_stub:
        provider_a = StubProvider("Kalshi")
        provider_b = StubProvider("Polymarket")
        run_scan(provider_a, provider_b)
        return 0

    if args.kalshi_market_prices:
        from arb_scanner.kalshi_public import KalshiPublicClient

        def is_mve(t: str) -> bool:
            return t.startswith("KXMVE") or ("MULTIGAMEEXTENDED" in t)

        client = KalshiPublicClient()

        # Ojo: en tu caso casi todo es MVE, así que si no expandes legs, no sale nada útil.
        max_pages = 1
        limit_per_page = 200

        markets = list(
            client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page)
        )

        tickers_to_price: list[str] = []
        seen: set[str] = set()

        for m in markets:
            t = (m.get("ticker") or "").strip()
            if not t:
                continue

            if is_mve(t):
                legs = m.get("mve_selected_legs") or []
                for leg in legs:
                    leg_ticker = (leg.get("market_ticker") or "").strip()
                    if not leg_ticker or leg_ticker in seen:
                        continue
                    tickers_to_price.append(leg_ticker)
                    seen.add(leg_ticker)
                continue

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

    if args.use_kalshi:
        from arb_scanner.sources.kalshi import KalshiProvider

        provider = KalshiProvider()
        snapshots = list(provider.fetch_market_snapshots())
        print(f"snapshots={len(snapshots)}")
        return 0

    # Default: nada
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
