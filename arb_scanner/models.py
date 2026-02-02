"""Dataclasses for markets and order books."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Market:
    venue: str
    market_id: str
    question: str
    outcomes: tuple[str, ...]

    @property
    def is_binary(self) -> bool:
        return len(self.outcomes) == 2 and {"yes", "no"} == {o.lower() for o in self.outcomes}


@dataclass(frozen=True)
class OrderBookTop:
    best_yes_price: float | None
    best_yes_size: float
    best_no_price: float | None
    best_no_size: float


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    orderbook: OrderBookTop


@dataclass(frozen=True)
class Opportunity:
    question: str
    outcomes: tuple[str, ...]
    buy_yes_venue: str
    buy_yes_price: float
    buy_no_venue: str
    buy_no_price: float
    sum_price: float
    executable_size: float
    edge: float


def normalize_question(question: str) -> str:
    return " ".join(question.lower().split())


def iter_pairs(
    markets_a: Iterable[MarketSnapshot], markets_b: Iterable[MarketSnapshot]
) -> Iterable[tuple[MarketSnapshot, MarketSnapshot]]:
    """
    Yield tuples of snapshots from two venues keyed by normalized question + outcomes.

    Nota: este helper sirve para el matching rápido. En cross-venue SAFE
    normalmente ya vienes con mappings/whitelist, así que no pretendemos
    “descubrir” matches por NLP aquí.
    """
    index: dict[tuple[str, tuple[str, ...]], MarketSnapshot] = {
        (normalize_question(ms.market.question), tuple(ms.market.outcomes)): ms for ms in markets_b
    }
    for ms in markets_a:
        key = (normalize_question(ms.market.question), tuple(ms.market.outcomes))
        match = index.get(key)
        if match:
            yield ms, match

