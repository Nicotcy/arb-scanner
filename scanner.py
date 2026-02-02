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
        help="Print Kalshi ticker suggestions for manual mappings (broad, includes sports).",
    )
    parser.add_argument(
        "--suggest-safe",
        action="store_true",
        help="Print ONLY 'safer' Kalshi candidates (non-sports by strict rules).",
    )

    return parser.parse_args()


def _is_any_sports(ticker: str) -> bool:
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
        "KXEPL",  # IMPORTANT: EPL también es deporte
        "KXSB",   # Super Bowl
    )
    return t.startswith(sports_prefixes)


def _looks_like_player_prop(ticker: str) -> bool:
    t = ticker.upper()
    prop_markers = (
        "PTS", "REB", "AST", "STL", "BLK", "3PT",
        "RSH", "PASS", "REC", "TD", "YDS",
        "GOALS", "SACK", "INT",
        "BTTS",  # both teams to score (soccer prop)
    )
    return any(m in t for m in prop_markers)


def _suggestions(
    tickers: Iterable[str],
    limit_safe: int = 25,
    limit_sports_non_props: int = 20,
) -> tuple[list[str], list[str], dict]:
    safe: list[str] = []
    sports_non_props: list[str] = []
    seen: set[str] = set()
    stats = Counter()

    for tk in tickers:
        if not tk or tk in seen:
            continue
        seen.add(tk)

        is_sports = _is_any_sports(tk)
        is_prop = _looks_like_player_prop(tk)

        if is_sports:
            stats["sports_total"] += 1
            if not is_prop and len(sports_non_props) < limit_sports_non_props:
                sports_non_props.append(tk)
                stats["sports_non_props_kept"] += 1
            else:
                stats["sports_skipped"] += 1
        else:
            stats["safe_total"] += 1
            if len(safe) < limit_safe:
                safe.append(tk)
                stats["safe_kept"] += 1

        if len(safe) >= limit_safe and len(sports_non_props) >= limit_sports_non_props:
            break

    return safe, sports_non_props, dict(stats)


def _print_mapping_suggestions(snapshots_a, safe_only: bool) -> None:
    kalshi_tickers = [s.market.market_id for s in snapshots_a]
    safe, sports_non_props, stats = _suggestions(kalshi_tickers, 25, 20)

    print("Suggestion stats:", stats)

    if safe:
        print("\nSAFE candidates (strict non-sports, top 25):")
        for tk in safe:
            print(f"  - {tk}")
    else:
        print("\nSAFE candidates: NONE found in this sample.")
        print("Meaning: current open Kalshi markets are basically sports. That's normal on many days.")

    if not safe_only:
        if sports_non_props:
            print("\nFALLBACK candidates (sports but NON-props) for pipeline testing ONLY (riskier, top 20):")
            for tk in sports_non_props:
                print(f"  - {tk}")
        else:
            print("\nFallback (sports non-props): NONE found.")


def main() -> int:
    args = parse_args()
    config = load_config()

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

    elif args.use_kalshi or args.use_mapping or args.suggest_mappings or args.suggest_safe:
        provider = KalshiProvider()
        snapshots_a = list(provider.fetch_market_snapshots())
        snapshots_b = []

        if args.suggest_mappings:
            print(summarize_config(config))
            _print_mapping_suggestions(snapshots_a, safe_only=False)
            return 0

        if args.suggest_safe:
            print(summarize_config(config))
            _print_mapping_suggestions(snapshots_a, safe_only=True)
            return 0

        if args.use_mapping:
            provider_b = PolymarketStubProvider()
            snapshots_b = list(provider_b.fetch_market_snapshots())

            mappings: list[MarketMapping] = load_manual_mappings()
            if not mappings:
                print(summarize_config(config))
                print("No manual mappings defined yet. Add mappings in arb_scanner/mappings.py\n")
                _print_mapping_suggestions(snapshots_a, safe_only=True)
                print("\nNext: if SAFE list is empty, stop trying to map from Kalshi today.")
                print("We will instead pick SAFE markets from Polymarket and search their Kalshi equivalents.")
                return 0

            print(summarize_config(config))
            print(f"Loaded {len(mappings)} manual mappings. (Polymarket is stub for now)")

    else:
        raise SystemExit(
            "Choose one: --use-stub, --use-kalshi, --use-mapping, --suggest-mappings, --suggest-safe, or --kalshi-market-prices"
        )

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
