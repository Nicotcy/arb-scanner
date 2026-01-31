from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

from arb_scanner.models import MarketSnapshot, Opportunity


def summarize_config(config: object) -> str:
    try:
        if hasattr(config, "__dataclass_fields__"):
            d = asdict(config)  # type: ignore[arg-type]
            return "CONFIG " + " ".join(f"{k}={v}" for k, v in d.items())
    except Exception:
        pass
    return f"CONFIG {config!r}"

_NEAR_MISS_ROWS: list[tuple[str, float, float, float, float, float]] = []


def compute_opportunities(
    a_snapshots: Sequence[MarketSnapshot],
    b_snapshots: Sequence[MarketSnapshot],
    min_edge: float = 0.0,
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

    opps.sort(key=lambda o: o.edge, reverse=True)
    return opps


def format_opportunity_table(opps: Sequence[Opportunity], limit: int = 25) -> str:
    if not opps:
        return "No opportunities found."

    lines: list[str] = []
    lines.append("edge  yes@venue(price)  no@venue(price)  question")
    lines.append("-" * 90)
    for o in opps[:limit]:
        lines.append(
            f"{o.edge:>5.3f}  {o.buy_yes_venue}({o.buy_yes_price:.3f})  "
            f"{o.buy_no_venue}({o.buy_no_price:.3f})  {o.question}"
        )
    return "\n".join(lines)


def run_scan(
    provider_a: object,
    provider_b: object,
    min_edge: float = 0.0,
) -> list[Opportunity]:
    a_snaps = list(getattr(provider_a, "fetch_market_snapshots")())
    b_snaps = list(getattr(provider_b, "fetch_market_snapshots")())
    return compute_opportunities(a_snaps, b_snaps, min_edge=min_edge)
