from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from arb_scanner.config import ScannerConfig
from arb_scanner.models import MarketSnapshot, Opportunity, iter_pairs


def summarize_config(config: ScannerConfig) -> str:
    return (
        "CONFIG "
        f"dry_run={config.dry_run} "
        f"alert_only={config.alert_only} "
        f"alert_threshold={config.alert_threshold} "
        f"fee_buffer_bps={config.fee_buffer_bps}"
    )


def _normalize_price_to_prob(price: float | None) -> float | None:
    """
    Normaliza precio a probabilidad 0..1.
    Kalshi suele venir en "cents" 0..100. Si viene ya en 0..1, lo deja.
    """
    if price is None:
        return None
    p = float(price)
    if p > 1.0:
        return p / 100.0
    return p


def _fee_buffer(cost: float, config: ScannerConfig) -> float:
    return cost * (config.fee_buffer_bps / 10_000.0)


def _fmt_float(x: float | None, nd: int = 6) -> str:
    if x is None:
        return "-"
    return f"{x:.{nd}f}"


def compute_opportunities(
    snapshots_a: Iterable[MarketSnapshot],
    snapshots_b: Iterable[MarketSnapshot],
    config: ScannerConfig,
) -> list[Opportunity]:
    """
    Cross-venue opportunities.
    Matching por (normalize_question(question), outcomes) vía iter_pairs() en models.py.
    """
    opps: list[Opportunity] = []

    for a, b in iter_pairs(snapshots_a, snapshots_b):
        # Necesitamos binarios y precios ask de ambos lados
        if not a.market.is_binary or not b.market.is_binary:
            continue

        a_yes = _normalize_price_to_prob(a.orderbook.best_yes_price)
        a_no = _normalize_price_to_prob(a.orderbook.best_no_price)
        b_yes = _normalize_price_to_prob(b.orderbook.best_yes_price)
        b_no = _normalize_price_to_prob(b.orderbook.best_no_price)

        # Caso 1: Buy YES en A + Buy NO en B
        if a_yes is not None and b_no is not None:
            cost = a_yes + b_no
            net_edge = 1.0 - cost - _fee_buffer(cost, config)
            if net_edge > 0:
                opps.append(
                    Opportunity(
                        question=a.market.question,
                        outcomes=tuple(a.market.outcomes),
                        buy_yes_venue=a.market.venue,
                        buy_yes_price=a_yes,
                        buy_no_venue=b.market.venue,
                        buy_no_price=b_no,
                        edge=net_edge,
                    )
                )

        # Caso 2: Buy YES en B + Buy NO en A
        if b_yes is not None and a_no is not None:
            cost = b_yes + a_no
            net_edge = 1.0 - cost - _fee_buffer(cost, config)
            if net_edge > 0:
                opps.append(
                    Opportunity(
                        question=a.market.question,
                        outcomes=tuple(a.market.outcomes),
                        buy_yes_venue=b.market.venue,
                        buy_yes_price=b_yes,
                        buy_no_venue=a.market.venue,
                        buy_no_price=a_no,
                        edge=net_edge,
                    )
                )

    opps.sort(key=lambda o: o.edge, reverse=True)
    return opps


def format_opportunity_table(opps: list[Opportunity], limit: int = 20) -> str:
    if not opps:
        return "No opportunities found."

    rows = opps[:limit]
    lines = []
    lines.append(
        "EDGE      | BUY YES (venue@price)        | BUY NO (venue@price)         | QUESTION"
    )
    lines.append("-" * 100)
    for o in rows:
        yes_part = f"{o.buy_yes_venue}@{_fmt_float(o.buy_yes_price, 6)}"
        no_part = f"{o.buy_no_venue}@{_fmt_float(o.buy_no_price, 6)}"
        q = o.question
        lines.append(f"{_fmt_float(o.edge, 6):<9} | {yes_part:<26} | {no_part:<26} | {q}")
    return "\n".join(lines)


def format_near_miss_pairs_table(
    snapshots_a: list[MarketSnapshot],
    snapshots_b: list[MarketSnapshot],
    config: ScannerConfig,
    limit: int = 20,
) -> str:
    """
    Near-miss ranking.
    - Si solo hay A (Kalshi): intra-market (yes_ask + no_ask) por snapshot.
    - Si hay A y B: cross-venue near-miss para pares (dos direcciones).
    """
    rows: list[dict] = []

    if not snapshots_b:
        # Intra-market near-miss (Kalshi standalone)
        for s in snapshots_a:
            if not s.market.is_binary:
                continue
            y = _normalize_price_to_prob(s.orderbook.best_yes_price)
            n = _normalize_price_to_prob(s.orderbook.best_no_price)
            if y is None or n is None:
                continue

            cost = y + n
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(s.orderbook.best_yes_size or 0), float(s.orderbook.best_no_size or 0))

            rows.append(
                {
                    "market_id": s.market.market_id,
                    "yes_ask": y,
                    "no_ask": n,
                    "sum_price": cost,
                    "edge": edge,
                    "executable_size": exe,
                }
            )
    else:
        # Cross-venue near-miss
        for a, b in iter_pairs(snapshots_a, snapshots_b):
            if not a.market.is_binary or not b.market.is_binary:
                continue

            a_yes = _normalize_price_to_prob(a.orderbook.best_yes_price)
            a_no = _normalize_price_to_prob(a.orderbook.best_no_price)
            b_yes = _normalize_price_to_prob(b.orderbook.best_yes_price)
            b_no = _normalize_price_to_prob(b.orderbook.best_no_price)

            # A yes + B no
            if a_yes is not None and b_no is not None:
                cost = a_yes + b_no
                edge = 1.0 - cost - _fee_buffer(cost, config)
                exe = min(
                    float(a.orderbook.best_yes_size or 0),
                    float(b.orderbook.best_no_size or 0),
                )
                rows.append(
                    {
                        "market_id": f"{a.market.venue}:{a.market.market_id} | {b.market.venue}:{b.market.market_id}",
                        "yes_ask": a_yes,
                        "no_ask": b_no,
                        "sum_price": cost,
                        "edge": edge,
                        "executable_size": exe,
                    }
                )

            # B yes + A no
            if b_yes is not None and a_no is not None:
                cost = b_yes + a_no
                edge = 1.0 - cost - _fee_buffer(cost, config)
                exe = min(
                    float(b.orderbook.best_yes_size or 0),
                    float(a.orderbook.best_no_size or 0),
                )
                rows.append(
                    {
                        "market_id": f"{b.market.venue}:{b.market.market_id} | {a.market.venue}:{a.market.market_id}",
                        "yes_ask": b_yes,
                        "no_ask": a_no,
                        "sum_price": cost,
                        "edge": edge,
                        "executable_size": exe,
                    }
                )

    if not rows:
        return ""

    rows.sort(key=lambda r: r["edge"], reverse=True)
    rows = rows[:limit]

    lines = []
    lines.append("MARKET_ID | YES_ASK | NO_ASK | SUM | EDGE | EXEC_SIZE")
    lines.append("-" * 95)
    for r in rows:
        lines.append(
            f"{r['market_id']} | "
            f"{_fmt_float(r['yes_ask'], 6)} | "
            f"{_fmt_float(r['no_ask'], 6)} | "
            f"{_fmt_float(r['sum_price'], 6)} | "
            f"{_fmt_float(r['edge'], 6)} | "
            f"{_fmt_float(r['executable_size'], 2)}"
        )
    return "\n".join(lines)
