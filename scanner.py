from __future__ import annotations

import argparse
import os
from collections import Counter
from typing import Iterable

from arb_scanner.config import load_config
from arb_scanner.mappings import load_manual_mappings, MarketMapping
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
    parser.add_argument(
        "--suggest-mappings",
        action="store_true",
        help="Print Kalshi ticker suggestions for manual mappings.",
    )

    return parser.parse_args()


def _looks_like_sports_ticker(ticker: str) -> bool:
    t = ticker.upper()
    sports_prefixes = (
        "KXNBA",
        "KXNFL",
        "KXNCA",
        "KXMLB",
        "KXNHL",
        "KXWNBA",
        "KXUFC",
        "KXSOCCER",
        "KXCFB",
        "KXNCAA",
    )
    return t.startswith(sports_prefixes)


def _looks_like_player_prop(ticker: str) -> bool:
    """
    Props típicos: pts/reb/ast/yds/td etc.
    Estos NO son buenos para 'seguro', pero sirven para testear pipeline si no hay otra cosa.
    """
    t = ticker.upper()
    prop_markers = (
        "PTS",
        "REB",
        "AST",
        "STL",
        "BLK",
        "3PT",
        "RSH",
        "PASS",
        "REC",
        "TD",
        "YDS",
        "GOALS",
        "SACK",
        "INT",
    )
    return any(m in t for m in prop_markers)


def _suggestions(
    tickers: Iterable[str],
    limit_non_sports: int = 20,
    limit_sports_non_props: int = 20,
) -> tuple[list[str], list[str], dict]:
    """
    Devuelve:
      - non_sports: tickers no deportivos (preferibles para mappings 'seguros')
      - sports_non_props: tickers deportivos pero no-props (para test/pipeline, riesgo alto)
      - stats: conteos de filtrado
    """
    non_sports: list[str] = []
    sports_non_props: list[str] = []
    seen: set[str] = set()

    stats = Counter()

    for tk in tickers:
        if not tk or tk in seen:
            continue
        seen.add(tk)

        is_sports = _looks_like_sports_ticker(tk)
        is_prop = _looks_like_player_prop(tk)

        if is_sports:
            stats["sports_total"] += 1
            if not is_prop and len(sports_non_props) < limit_sports_non_props:
                sports_non_props.append(tk)
                stats["sports_non_props_kept"] += 1
            else:
                stats["sports_props_skipped"] += 1
        else:
            stats["non_sports_total"] += 1
            if len(non_sports) < limit_non_sports:
                non_sports.append(tk)
                stats["non_sports_kept"] += 1

        if len(non_sports) >= limit_non_sports and len(sports_non_props) >= limit_sports_non_props:
            break

    return non_sports, sports_non_props, dict(stats)


def _print_mapping_suggestions(snapshots_a) -> None:
    kalshi_tickers = [s.market.market_id for s in snapshots_a]
    non_sports, sports_non_props, stats = _suggestions(kalshi_tickers, 20, 20)

    print("Suggestion stats:", stats)

    if non_sports:
        print("\nPreferred (non-sports) Kalshi mapping candidates (top 20):")
        for tk in non_sports:
            print(f"  - {tk}")
    else:
        print("\nPreferred (non-sports) Kalshi mapping candidates: NONE found in this sample.")
        print("This likely means current open markets are dominated by sports.")

    if sports_non_props:
        print("\nFallback (sports but NON-props) candidates for pipeline testing (riskier, top 20):")
        for tk in sports_non_props:
            print(f"  - {tk}")
    else:
        print("\nFallback (sports non-props): NONE found.")


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

    elif args.use_kalshi or args.use_mapping or args.suggest_mappings:
        provider = KalshiProvider()
        snapshots_a = list(provider.fetch_market_snapshots())
        snapshots_b = []

        if args.suggest_mappings and not args.use_mapping:
            print(summarize_config(config))
            _print_mapping_suggestions(snapshots_a)
            return 0

        if args.use_mapping:
            provider_b = PolymarketStubProvider()
            snapshots_b = list(provider_b.fetch_market_snapshots())

            mappings: list[MarketMapping] = load_manual_mappings()
            if not mappings:
                print(summarize_config(config))
                print("No manual mappings defined yet. Add mappings in arb_scanner/mappings.py")
                _print_mapping_suggestions(snapshots_a)
                print("\nNext: pick ~10 preferred non-sports tickers (if any) and map to Polymarket slugs.")
                print('Example: MarketMapping(kalshi_ticker="KX....", polymarket_slug="some-polymarket-slug")')
                return 0

            print(summarize_config(config))
            print(f"Loaded {len(mappings)} manual mappings. (Polymarket is stub for now)")

    else:
        raise SystemExit("Choose one: --use-stub, --use-kalshi, --use-mapping, --suggest-mappings, or --kalshi-market-prices")

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
