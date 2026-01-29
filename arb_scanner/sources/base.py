"""Base interfaces for market data providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from arb_scanner.models import MarketSnapshot


class MarketDataProvider(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        raise NotImplementedError
