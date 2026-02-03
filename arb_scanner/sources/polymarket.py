from __future__ import annotations

import os
from dataclasses import dataclass

from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.mappings import MarketMapping
from arb_scanner.polymarket_public import PolymarketPublicClient


@dataclass
class PolymarketProvider:
    """
    Read-only provider for Polymarket using manual mappings.

    Robust behavior:
      - If mappings don't have YES/NO token IDs yet, resolve them via Gamma.
      - If a request fails, optionally log when POLY_HTTP_DEBUG=1.
    """

    mappings: list[MarketMapping]
    client: PolymarketPublicClient | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = PolymarketPublicClient()

        self._debug = os.getenv("POLY_HTTP_DEBUG", "0") == "1"
        # cache slug -> (yes_id, no_id)
        self._token_cache: dict[str, tuple[str, str]] = {}

    def _log(self, msg: str) -> None:
        if self._debug:
            print(f"[poly_http] {msg}")

    def _resolve_tokens(self, mp: MarketMapping) -> tuple[str, str] | None:
        assert self.client is not None

        # prefer mapping-provided token ids
        if mp.polymarket_yes_token_id and mp.polymarket_no_token_id:
            return (mp.polymarket_yes_token_id, mp.polymarket_no_token_id)

        # cache hit
        if mp.polymarket_slug in self._token_cache:
            return self._token_cache[mp.polymarket_slug]

        self._log(f"resolve slug -> tokens: {mp.polymarket_slug}")
        pair = self.client.resolve_slug_to_yes_no_token_ids(mp.polymarket_slug)
        if not pair:
            self._log(f"resolve FAILED (not strict Yes/No or not found): {mp.polymarket_slug}")
            return None

        yes_id, no_id = pair
        self._token_cache[mp.polymarket_slug] = (yes_id, no_id)
        return (yes_id, no_id)

    def fetch_market_snapshots(self):
        assert self.client is not None

        for mp in self.mappings:
            pair = self._resolve_tokens(mp)
            if not pair:
                continue
            yes_id, no_id = pair

            try:
                self._log(f"GET orderbook yes={yes_id[:10]}.. no={no_id[:10]}.. slug={mp.polymarket_slug}")
                yes_book = self.client.get_order_book_summary(yes_id)
                no_book = self.client.get_order_book_summary(no_id)
            except Exception as e:
                self._log(f"orderbook EXCEPTION {type(e).__name__}: {e}")
                continue

            if not yes_book.best_ask or not no_book.best_ask:
                self._log(f"empty best_ask (yes={bool(yes_book.best_ask)} no={bool(no_book.best_ask)}) slug={mp.polymarket_slug}")
                continue

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

            yield MarketSnapshot(market=market, orderbook=orderbook)
