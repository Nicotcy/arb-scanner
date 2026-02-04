from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from arb_scanner.mappings import MarketMapping
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.polymarket_public import PolymarketPublicClient
from arb_scanner.sources.base import MarketDataProvider


@dataclass
class PolymarketStats:
    total_mappings: int = 0
    resolved: int = 0
    missing_tokens: int = 0
    book_errors: int = 0
    noprices: int = 0
    ok: int = 0


class PolymarketProvider(MarketDataProvider):
    """
    Read-only Polymarket provider using public CLOB + Gamma APIs.

    Diseño consciente:
    - No se escanea todo Polymarket.
    - Solo se consultan los markets definidos en mappings.json.
    - Esto es suficiente (y necesario) para arbitraje cross-venue.
    """

    def __init__(self, mappings: list[MarketMapping]) -> None:
        self.mappings = list(mappings)
        self.client = PolymarketPublicClient()
        self._question_cache: dict[str, str] = {}

    def name(self) -> str:
        return "Polymarket"

    def _get_question_for_slug(self, slug: str) -> str:
        if slug in self._question_cache:
            return self._question_cache[slug]

        try:
            market = self.client.gamma_get_market_by_slug(slug)
        except Exception:
            market = None

        question = None
        if isinstance(market, dict):
            question = (
                market.get("question")
                or market.get("title")
                or market.get("name")
            )

        if not question:
            question = slug

        question = str(question)
        self._question_cache[slug] = question
        return question

    def _resolve_tokens(self, mapping: MarketMapping) -> tuple[str, str] | None:
        if mapping.polymarket_yes_token_id and mapping.polymarket_no_token_id:
            return mapping.polymarket_yes_token_id, mapping.polymarket_no_token_id

        try:
            return self.client.resolve_slug_to_yes_no_token_ids(
                mapping.polymarket_slug
            )
        except Exception:
            return None

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        stats = PolymarketStats(total_mappings=len(self.mappings))

        for mp in self.mappings:
            tokens = self._resolve_tokens(mp)
            if not tokens:
                stats.missing_tokens += 1
                continue

            yes_token, no_token = tokens
            stats.resolved += 1

            try:
                yes_book = self.client.get_order_book_summary(yes_token)
                no_book = self.client.get_order_book_summary(no_token)
            except Exception:
                stats.book_errors += 1
                continue

            if yes_book.best_ask is None or no_book.best_ask is None:
                stats.noprices += 1
                continue

            yes_price = float(yes_book.best_ask.price)
            no_price = float(no_book.best_ask.price)
            yes_size = float(yes_book.best_ask.size)
            no_size = float(no_book.best_ask.size)

            orderbook = OrderBookTop(
                best_yes_price=yes_price,
                best_yes_size=yes_size,
                best_no_price=no_price,
                best_no_size=no_size,
            )

            market = Market(
                venue="Polymarket",
                market_id=mp.polymarket_slug,
                question=self._get_question_for_slug(mp.polymarket_slug),
                outcomes=("YES", "NO"),
            )

            stats.ok += 1
            yield MarketSnapshot(
                market=market,
                orderbook=orderbook,
            )

        print(
            "PolymarketProvider stats: "
            f"mappings={stats.total_mappings} "
            f"ok={stats.ok} "
            f"resolved={stats.resolved} "
            f"missing_tokens={stats.missing_tokens} "
            f"book_errors={stats.book_errors} "
            f"noprices={stats.noprices}"
        )
