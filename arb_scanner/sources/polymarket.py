from __future__ import annotations

from dataclasses import dataclass

from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.mappings import MarketMapping
from arb_scanner.polymarket_public import PolymarketPublicClient


@dataclass
class PolymarketProvider:
    """
    Read-only provider for Polymarket using manual mappings.

    Emits MarketSnapshot objects compatible with the core scanner.
    Prices are probabilities in [0, 1].
    """

    mappings: list[MarketMapping]
    client: PolymarketPublicClient | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = PolymarketPublicClient()

    def fetch_market_snapshots(self):
        assert self.client is not None

        for mp in self.mappings:
            # Require resolved YES / NO token IDs
            if not mp.polymarket_yes_token_id or not mp.polymarket_no_token_id:
                continue

            try:
                yes_book = self.client.get_order_book_summary(mp.polymarket_yes_token_id)
                no_book = self.client.get_order_book_summary(mp.polymarket_no_token_id)
            except Exception:
                continue

            if not yes_book.best_ask or not no_book.best_ask:
                continue

            # Minimal but valid Market object
            market = Market(
                venue="Polymarket",
                market_id=mp.polymarket_slug,
                question=mp.polymarket_slug.replace("-", " ").capitalize(),
                outcomes=["YES", "NO"],
            )

            orderbook = OrderBookTop(
                best_yes_price=yes_book.best_ask.price,
                best_no_price=no_book.best_ask.price,
                best_yes_size=yes_book.best_ask.size,
                best_no_size=no_book.best_ask.size,
            )

            yield MarketSnapshot(
                market=market,
                orderbook=orderbook,
            )
