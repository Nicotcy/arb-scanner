"""Kalshi market data provider (read-only via public API)."""

from __future__ import annotations

from collections.abc import Iterable
import os

from arb_scanner.kalshi_public import KalshiPublicClient
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
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
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
                
        total_tickers = 0
        fetched_ok = 0
        fetch_errors = 0
        no_bids_both_sides = 0
        one_sided_only = 0
        two_sided = 0
        for market in markets:
            if total_tickers >= max_tickers:
                break
            ticker = market.get("ticker")
            if not ticker:
                continue
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
            if not has_any_bid:
                no_bids_both_sides += 1
                continue
            if has_yes_ask and has_no_ask:
                two_sided += 1
            else:
                one_sided_only += 1
            if not (has_yes_ask or has_no_ask):
                continue
            yes_size = float(top.no_bid_qty or 0)
            no_size = float(top.yes_bid_qty or 0)
            snapshot = MarketSnapshot(
                market=Market(
                    venue=self.name(),
                    market_id=ticker,
                    question=market.get("title") or ticker,
                    outcomes=("Yes", "No"),
                ),
                orderbook=OrderBookTop(
                    best_yes_price=top.yes_ask,
                    best_yes_size=yes_size,
                    best_no_price=top.no_ask,
                    best_no_size=no_size,
                ),
            )
            yield snapshot
        print(
            "KalshiProvider stats: "
            f"total={total_tickers} "
            f"ok={fetched_ok} "
            f"errors={fetch_errors} "
            f"nobids={no_bids_both_sides} "
            f"one_sided={one_sided_only} "
            f"two_sided={two_sided}"
        )
