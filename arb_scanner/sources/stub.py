"""Stub data provider for offline testing."""

from __future__ import annotations

from collections.abc import Iterable

from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


class StubProvider(MarketDataProvider):
    def __init__(self, venue: str) -> None:
        self._venue = venue

    def name(self) -> str:
        return self._venue

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        markets = [
            Market(
                venue=self._venue,
                market_id=f"{self._venue}-btc-2025",
                question="Will Bitcoin close above $100k on 2025-12-31?",
                outcomes=("Yes", "No"),
            ),
            Market(
                venue=self._venue,
                market_id=f"{self._venue}-nfl-2025",
                question="Will the Chiefs win the 2025 Super Bowl?",
                outcomes=("Yes", "No"),
            ),
        ]

        books = [
            OrderBookTop(best_yes_price=0.52, best_yes_size=120.0, best_no_price=0.49, best_no_size=80.0),
            OrderBookTop(best_yes_price=0.35, best_yes_size=200.0, best_no_price=0.68, best_no_size=140.0),
        ]

        for market, book in zip(markets, books, strict=True):
            yield MarketSnapshot(market=market, orderbook=book)
