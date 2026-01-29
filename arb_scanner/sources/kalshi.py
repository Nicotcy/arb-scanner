"""Kalshi market data provider (requires official API wiring)."""

from __future__ import annotations

from collections.abc import Iterable

from arb_scanner.models import MarketSnapshot
from arb_scanner.sources.base import MarketDataProvider


class KalshiProvider(MarketDataProvider):
    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        raise NotImplementedError("Wire Kalshi REST API market + orderbook fetching here.")
