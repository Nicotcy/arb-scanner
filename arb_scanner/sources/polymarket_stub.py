from __future__ import annotations

from collections.abc import Iterable

from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


class PolymarketStubProvider(MarketDataProvider):
    """
    Stub temporal para Polymarket: devuelve snapshots vacíos.
    Sirve para cablear el pipeline sin depender aún de la API.
    """

    def __init__(self) -> None:
        pass

    def name(self) -> str:
        return "Polymarket"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        # De momento no devuelve nada.
        # Lo reemplazaremos por el provider real cuando definamos el fetch de orderbook.
        return []
        yield  # pragma: no cover
