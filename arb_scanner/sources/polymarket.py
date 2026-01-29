"""Polymarket market data provider (requires pmxt or direct HTTP wiring)."""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable

from arb_scanner.models import MarketSnapshot
from arb_scanner.sources.base import MarketDataProvider


class PolymarketProvider(MarketDataProvider):
    def name(self) -> str:
        return "Polymarket"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        pmxt_spec = importlib.util.find_spec("pmxt")
        if pmxt_spec is None:
            raise RuntimeError(
                "pmxt is not installed. Install pmxt or replace this provider with your own implementation."
            )
        raise NotImplementedError("Wire pmxt market + orderbook fetching here.")
