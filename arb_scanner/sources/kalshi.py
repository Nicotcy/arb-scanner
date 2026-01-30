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
        for key in ("volume_24h", "volume", "open_interest"):
            active_markets = [
                market
                for market in markets
                if (market.get(key) or 0) > 0
            ]
            if active_markets:
                markets = sorted(
                    active_markets,
                    key=lambda market: market.get(key) or 0,
                    reverse=True,
                )
                break
        for market in markets:
            ticker = market.get("ticker")
            if not ticker:
                continue
            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                continue
            if top.yes_ask is None or top.no_ask is None:
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
