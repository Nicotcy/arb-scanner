"""Scanner logic for candidate cross-market arbitrage."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from arb_scanner.config import ScannerConfig
from arb_scanner.models import MarketSnapshot, Opportunity, format_opportunity, iter_pairs


def compute_opportunities(
    markets_a: Iterable[MarketSnapshot],
    markets_b: Iterable[MarketSnapshot],
    config: ScannerConfig,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []

    for snap_a, snap_b in iter_pairs(markets_a, markets_b):
        yes_price = snap_a.orderbook.best_yes_price
        no_price = snap_b.orderbook.best_no_price
        hedge_cost = yes_price + no_price
        estimated_fees = hedge_cost * (config.fee_buffer_bps / 10_000)
        top_liquidity = min(snap_a.orderbook.best_yes_size, snap_b.orderbook.best_no_size)
        market_mismatch = not (snap_a.market.is_binary and snap_b.market.is_binary)
        net_edge = 1.0 - (hedge_cost + estimated_fees)

        opportunities.append(
            Opportunity(
                market_pair=f"{snap_a.market.venue}:{snap_a.market.market_id} vs {snap_b.market.venue}:{snap_b.market.market_id}",
                best_yes_price_A=yes_price,
                best_no_price_B=no_price,
                hedge_cost=hedge_cost,
                estimated_fees=estimated_fees,
                top_of_book_liquidity=top_liquidity,
                market_mismatch=market_mismatch,
                net_edge=net_edge,
            )
        )

    return opportunities


def format_opportunity_table(opportunities: Iterable[Opportunity]) -> str:
    lines = [format_opportunity(opportunity) for opportunity in opportunities]
    return "\n".join(lines)


def summarize_config(config: ScannerConfig) -> str:
    values = asdict(config)
    return ", ".join(f"{key}={value}" for key, value in values.items())
