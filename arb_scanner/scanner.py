"""Scanner logic for candidate cross-market arbitrage."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from arb_scanner.config import ScannerConfig
from arb_scanner.models import MarketSnapshot, Opportunity, format_opportunity, iter_pairs

_NEAR_MISS_ROWS: list[tuple[str, float, float, float, float, float]] = []


def compute_opportunities(
    markets_a: Iterable[MarketSnapshot],
    markets_b: Iterable[MarketSnapshot],
    config: ScannerConfig,
) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    _NEAR_MISS_ROWS.clear()

    for snap_a, snap_b in iter_pairs(markets_a, markets_b):
        yes_price = snap_a.orderbook.best_yes_price
        no_price = snap_b.orderbook.best_no_price
        if (
            snap_a.market.is_binary
            and snap_b.market.is_binary
            and yes_price is not None
            and no_price is not None
        ):
            sum_price = yes_price + no_price
            edge = 1.0 - sum_price
            executable_size = min(
                snap_a.orderbook.best_yes_size, snap_b.orderbook.best_no_size
            )
            _NEAR_MISS_ROWS.append(
                (
                    f"{snap_a.market.venue}:{snap_a.market.market_id} vs "
                    f"{snap_b.market.venue}:{snap_b.market.market_id}",
                    yes_price,
                    no_price,
                    sum_price,
                    edge,
                    executable_size,
                )
            )
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


def format_near_miss_table(markets: Iterable[MarketSnapshot]) -> str:
    rows: list[tuple[str, float, float, float, float, float, float]] = []
    for snapshot in markets:
        if not snapshot.market.is_binary:
            continue
        yes_ask = snapshot.orderbook.best_yes_price
        no_ask = snapshot.orderbook.best_no_price
        if yes_ask is None or no_ask is None:
            continue
        yes_qty = snapshot.orderbook.best_yes_size
        no_qty = snapshot.orderbook.best_no_size
        sum_price = yes_ask + no_ask
        edge = 1.0 - sum_price
        rows.append(
            (
                snapshot.market.market_id,
                yes_ask,
                yes_qty,
                no_ask,
                no_qty,
                sum_price,
                edge,
            )
        )

    if not rows:
        return ""

    rows.sort(key=lambda row: row[-1], reverse=True)
    rows = rows[:20]

    lines = [
        "market_id yes_ask yes_qty no_ask no_qty sum_price edge",
    ]
    for (
        market_id,
        yes_ask,
        yes_qty,
        no_ask,
        no_qty,
        sum_price,
        edge,
    ) in rows:
        lines.append(
            f"{market_id} "
            f"{yes_ask:.4f} "
            f"{yes_qty:.4f} "
            f"{no_ask:.4f} "
            f"{no_qty:.4f} "
            f"{sum_price:.4f} "
            f"{edge:.4f}"
        )
    return "\n".join(lines)


def format_near_miss_pairs_table() -> str:
    if not _NEAR_MISS_ROWS:
        return ""
    rows = sorted(_NEAR_MISS_ROWS, key=lambda row: row[4], reverse=True)[:20]
    lines = [
        "market_id yes_ask no_ask sum_price edge executable_size",
    ]
    for market_id, yes_ask, no_ask, sum_price, edge, executable_size in rows:
        lines.append(
            f"{market_id} "
            f"{yes_ask:.4f} "
            f"{no_ask:.4f} "
            f"{sum_price:.4f} "
            f"{edge:.4f} "
            f"{executable_size:.4f}"
        )
    return "\n".join(lines)
