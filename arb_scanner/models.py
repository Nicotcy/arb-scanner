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
    best_yes_price: float
    best_yes_size: float
    best_no_price: float
    best_no_size: float


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    orderbook: OrderBookTop


@dataclass(frozen=True)
class Opportunity:
    market_pair: str
    best_yes_price_A: float
    best_no_price_B: float
    hedge_cost: float
    estimated_fees: float
    top_of_book_liquidity: float
    market_mismatch: bool
    net_edge: float


def format_opportunity(opportunity: Opportunity) -> str:
    """Format opportunity for human-readable output."""

    mismatch = "YES" if opportunity.market_mismatch else "NO"
    return (
        f"{opportunity.market_pair} | "
        f"best_yes_price_A={opportunity.best_yes_price_A:.4f} | "
        f"best_no_price_B={opportunity.best_no_price_B:.4f} | "
        f"hedge_cost={opportunity.hedge_cost:.4f} | "
        f"estimated_fees={opportunity.estimated_fees:.4f} | "
        f"top_of_book_liquidity={opportunity.top_of_book_liquidity:.2f} | "
        f"market_mismatch={mismatch} | "
        f"net_edge={opportunity.net_edge:.2%}"
    )


def iter_pairs(markets_a: Iterable[MarketSnapshot], markets_b: Iterable[MarketSnapshot]):
    """Yield tuples of snapshots from two venues keyed by question text."""

    index = {normalize_question(ms.market.question): ms for ms in markets_b}
    for ms in markets_a:
        key = normalize_question(ms.market.question)
        match = index.get(key)
        if match:
            yield ms, match


def normalize_question(question: str) -> str:
    return " ".join(question.lower().split())
