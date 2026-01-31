"""Kalshi market data provider (read-only via public API)."""

from __future__ import annotations

from collections.abc import Iterable
import os

from arb_scanner.kalshi_public import KalshiPublicClient, normalize_kalshi_price
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


class KalshiProvider(MarketDataProvider):
    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        client = KalshiPublicClient()
        max_pages = int(os.getenv("KALSHI_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))
        markets = list(
            client.list_open_markets(
                max_pages=max_pages, limit_per_page=limit_per_page
            )
        )
        markets_raw = markets
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
        blacklist_substrings = ("MULTIGAMEEXTENDED",)
        markets_filtered = [
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
        min_after_blacklist = int(os.getenv("KALSHI_MIN_AFTER_BLACKLIST", "50"))
        if len(markets_filtered) < min_after_blacklist:
            print(
                "KalshiProvider: blacklist too aggressive "
                f"(filtered={len(markets_filtered)} raw={len(markets_raw)}); using raw"
            )
            markets = markets_raw
        else:
            markets = markets_filtered
        min_active = int(os.getenv("KALSHI_MIN_ACTIVE", "50"))
        max_tickers = int(os.getenv("KALSHI_MAX_TICKERS", "300"))
        for key in ("volume_24h", "volume", "open_interest"):
            active_markets = [
                market
                for market in markets
                if (market.get(key) or 0) > 0
            ]
            if len(active_markets) >= min_active:
                markets = sorted(
                    active_markets,
                    key=lambda market: market.get(key) or 0,
                    reverse=True,
                )
                break
        tickers_to_fetch: list[str] = []
        seen_tickers: set[str] = set()
        for market in markets:
            ticker = market.get("ticker")
            if ticker:
                if ticker not in seen_tickers:
                    tickers_to_fetch.append(ticker)
                    seen_tickers.add(ticker)
                continue
            legs = market.get("mve_selected_legs") or []
            for leg in legs:
                leg_ticker = leg.get("market_ticker")
                if not leg_ticker or leg_ticker in seen_tickers:
                    continue
                tickers_to_fetch.append(leg_ticker)
                seen_tickers.add(leg_ticker)
        total_tickers = 0
        fetched_ok = 0
        fetch_errors = 0
        no_asks_both_sides = 0
        one_sided_only = 0
        two_sided = 0
        require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") == "1"
        min_liq = float(os.getenv("KALSHI_MIN_LIQ", "1"))
        for ticker in tickers_to_fetch:
            if total_tickers >= max_tickers:
                break
            total_tickers += 1
            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                fetch_errors += 1
                continue
            fetched_ok += 1
            has_any_bid = top.yes_bid is not None or top.no_bid is not None
            has_yes_ask = top.yes_ask is not None
            has_no_ask = top.no_ask is not None
            if not has_yes_ask and not has_no_ask:
                no_asks_both_sides += 1
                continue
            if has_yes_ask and has_no_ask:
                two_sided += 1
            else:
                one_sided_only += 1
            if require_two_sided and not (has_yes_ask and has_no_ask):
                continue
            yes_size = float(top.yes_ask_qty or 0)
            no_size = float(top.no_ask_qty or 0)
            yes_ask = normalize_kalshi_price(top.yes_ask)
            no_ask = normalize_kalshi_price(top.no_ask)
            if has_yes_ask and has_no_ask and min(yes_size, no_size) < min_liq:
                continue
            snapshot = MarketSnapshot(
                market=Market(
                    venue=self.name(),
                    market_id=ticker,
                    question=ticker,
                    outcomes=("Yes", "No"),
                ),
                orderbook=OrderBookTop(
                    best_yes_price=yes_ask,
                    best_yes_size=yes_size,
                    best_no_price=no_ask,
                    best_no_size=no_size,
                ),
            )
            yield snapshot
        print(
            "KalshiProvider stats: "
            f"total={total_tickers} "
            f"ok={fetched_ok} "
            f"errors={fetch_errors} "
            f"noasks={no_asks_both_sides} "
            f"one_sided={one_sided_only} "
            f"two_sided={two_sided}"
        )
