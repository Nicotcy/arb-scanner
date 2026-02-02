from __future__ import annotations

import argparse
import os
from collections import Counter
from dataclasses import replace

from arb_scanner.config import apply_mode, load_config
from arb_scanner.mappings import load_manual_mappings, MarketMapping
from arb_scanner.polymarket_public import PolymarketPublicClient
from arb_scanner.scanner import (
    compute_opportunities,
    compute_opportunities_from_mapping_pairs,
    format_near_miss_pairs_table,
    format_near_miss_pairs_table_from_mapping_pairs,
    format_opportunity_table,
    summarize_config,
)
from arb_scanner.sources.kalshi import KalshiProvider
from arb_scanner.sources.polymarket import PolymarketProvider
from arb_scanner.sources.polymarket_stub import PolymarketStubProvider
from arb_scanner.sources.stub import StubProvider


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["lab", "safe"],
        default=os.getenv("MODE", "lab"),
        help="Policy mode: lab (more observability) vs safe (stricter thresholds/liq).",
    )

    parser.add_argument("--use-stub", action="store_true", help="Use stub providers.")
    parser.add_argument("--use-kalshi", action="store_true", help="Use Kalshi read-only snapshots.")
    parser.add_argument(
        "--use-mapping",
        action="store_true",
        help="Use manual Kalshi<->Polymarket mappings (Polymarket real read-only).",
    )
    parser.add_argument(
        "--use-mapping-stub",
        action="store_true",
        help="Use manual mappings but Polymarket STUB (debug only).",
    )
    parser.add_argument(
        "--kalshi-market-prices",
        action="store_true",
        help="Print sample Kalshi market prices using expanded leg tickers + top-of-book.",
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
        "KXEPL",
        "KXSB",
    )
    return t.startswith(sports_prefixes)


def _looks_like_player_prop(ticker: str) -> bool:
    t = ticker.upper()
    prop_markers = (
        "PTS", "REB", "AST", "STL", "BLK", "3PT",
        "RSH", "PASS", "REC", "TD", "YDS",
        "GOALS", "SACK", "INT",
        "BTTS",
    )
    return any(m in t for m in prop_markers)


def _suggestions(tickers, limit_safe: int = 25) -> tuple[list[str], dict]:
    safe: list[str] = []
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
            stats["sports_skipped"] += 1
            continue

        if is_prop:
            stats["non_sports_props_skipped"] += 1
            continue

        stats["safe_total"] += 1
        if len(safe) < limit_safe:
            safe.append(tk)
            stats["safe_kept"] += 1

        if len(safe) >= limit_safe:
            break

    return safe, dict(stats)


def _resolve_polymarket_tokens(mappings: list[MarketMapping]) -> list[MarketMapping]:
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


def main() -> int:
    args = parse_args()

    config = load_config()
    config = apply_mode(config, args.mode)

    if not config.dry_run:
        raise SystemExit("DRY_RUN must remain enabled for this scanner.")

    snapshots_a = []
    snapshots_b = []
    resolved_mappings: list[MarketMapping] | None = None

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

    else:
        provider_a = KalshiProvider()
        snapshots_a = list(provider_a.fetch_market_snapshots())

        if args.suggest_safe:
            safe, stats = _suggestions([s.market.market_id for s in snapshots_a])
            print(summarize_config(config))
            print("Suggestion stats:", stats)
            if safe:
                print("\nSAFE candidates (strict non-sports, top 25):")
                for tk in safe:
                    print(f"  - {tk}")
            else:
                print("\nSAFE candidates: NONE found in this sample.")
                print("Meaning: current open Kalshi markets are basically sports.")
            return 0

        if args.use_kalshi:
            snapshots_b = []

        elif args.use_mapping_stub:
            mappings = load_manual_mappings()
            if not mappings:
                print(summarize_config(config))
                print("No manual mappings defined yet. Add mappings in arb_scanner/mappings.py")
                return 0
            resolved_mappings = mappings
            provider_b = PolymarketStubProvider()
            snapshots_b = list(provider_b.fetch_market_snapshots())

        elif args.use_mapping:
            mappings = load_manual_mappings()
            if not mappings:
                print(summarize_config(config))
                print("No manual mappings defined yet. Add mappings in arb_scanner/mappings.py")
                return 0

            resolved = _resolve_polymarket_tokens(mappings)
            unresolved = [m for m in resolved if not (m.polymarket_yes_token_id and m.polymarket_no_token_id)]
            if unresolved:
                print(summarize_config(config))
                print("Some mappings could not be resolved to token IDs via Gamma.")
                for m in unresolved:
                    print(f"  - {m.polymarket_slug} (kalshi={m.kalshi_ticker})")
                print("\nFix: check the slug (must match Polymarket slug exactly).")
                return 0

            resolved_mappings = resolved
            provider_b = PolymarketProvider(mappings=resolved)
            snapshots_b = list(provider_b.fetch_market_snapshots())

        else:
            raise SystemExit(
                "Choose one: --use-kalshi, --use-mapping, --use-mapping-stub, --suggest-safe, or --kalshi-market-prices"
            )

    print(summarize_config(config))

    opportunities = []
    if snapshots_b:
        # When mappings exist, pair explicitly by mapping (NOT by question text).
        if resolved_mappings:
            opportunities = compute_opportunities_from_mapping_pairs(snapshots_a, snapshots_b, resolved_mappings, config)
        else:
            opportunities = compute_opportunities(snapshots_a, snapshots_b, config)

    if opportunities:
        print(format_opportunity_table(opportunities))
    else:
        print("No opportunities found.")

    if snapshots_b and resolved_mappings:
        near_miss_pairs = format_near_miss_pairs_table_from_mapping_pairs(
            snapshots_a, snapshots_b, resolved_mappings, config
        )
    else:
        near_miss_pairs = format_near_miss_pairs_table(snapshots_a, snapshots_b, config)

    if near_miss_pairs:
        print("Near-miss opportunities (top 20):")
        print(near_miss_pairs)
    else:
        print("No valid binary markets for near-miss table.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
