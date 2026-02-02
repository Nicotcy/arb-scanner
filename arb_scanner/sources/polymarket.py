from __future__ import annotations

from dataclasses import dataclass

from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.mappings import MarketMapping
from arb_scanner.polymarket_public import PolymarketPublicClient


@dataclass
class PolymarketProvider:
    """
    Read-only provider that emits MarketSnapshots for a given mapping list.
    We treat each mapped Polymarket market as binary with YES/NO outcome tokens.

    Prices from CLOB are already in [0,1] typical for Polymarket binary markets.
    We use BEST ASK for cost-to-buy YES and cost-to-buy NO. :contentReference[oaicite:6]{index=6}
    """

    mappings: list[MarketMapping]
    client: PolymarketPublicClient | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = PolymarketPublicClient()

    def fetch_market_snapshots(self):
        assert self.client is not None

        for mp in self.mappings:
            if not mp.polymarket_slug:
                continue

            yes_id = mp.polymarket_yes_token_id
            no_id = mp.polymarket_no_token_id
            if not yes_id or not no_id:
                # mapping not resolvable yet
                continue

            try:
                yes_book = self.client.get_order_book_summary(yes_id)
                no_book = self.client.get_order_book_summary(no_id)
            except Exception:
                continue

            yes_ask = yes_book.best_ask.price if yes_book.best_ask else None
            yes_ask_sz = yes_book.best_ask.size if yes_book.best_ask else None

            no_ask = no_book.best_ask.price if no_book.best_ask else None
            no_ask_sz = no_book.best_ask.size if no_book.best_ask else None

            if yes_ask is None or no_ask is None:
                continue

            market = Market(
                venue="Polymarket",
                market_id=mp.polymarket_slug,
                is_binary=True,
            )
            ob = OrderBookTop(
                best_yes_price=yes_ask,
                best_no_price=no_ask,
                best_yes_size=yes_ask_sz,
                best_no_size=no_ask_sz,
            )
            yield MarketSnapshot(market=market, orderbook=ob)
