from __future__ import annotations

from typing import Iterable

from arb_scanner.config import ScannerConfig
from arb_scanner.models import MarketSnapshot, Opportunity, iter_pairs


def summarize_config(config: ScannerConfig) -> str:
    return (
        "CONFIG "
        f"dry_run={config.dry_run} "
        f"mode={config.mode} "
        f"min_edge_opportunity={config.min_edge_opportunity} "
        f"min_exec_size={config.min_executable_size} "
        f"near_miss_floor={config.near_miss_edge_floor} "
        f"include_weird_sums={config.near_miss_include_weird_sums} "
        f"alert_only={config.alert_only} "
        f"alert_threshold={config.alert_threshold} "
        f"fee_buffer_bps={config.fee_buffer_bps}"
    )


def _normalize_price_to_prob(price: float | None) -> float | None:
    """
    Normalize price to probability 0..1.
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


def _min_edge_for_opportunities(config: ScannerConfig) -> float:
    # Backwards compat: ALERT_ONLY uses ALERT_THRESHOLD as the gate.
    if config.alert_only:
        return config.alert_threshold
    return config.min_edge_opportunity


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
    min_edge = _min_edge_for_opportunities(config)

    for a, b in iter_pairs(snapshots_a, snapshots_b):
        if not a.market.is_binary or not b.market.is_binary:
            continue

        a_yes = _normalize_price_to_prob(a.orderbook.best_yes_price)
        a_no = _normalize_price_to_prob(a.orderbook.best_no_price)
        b_yes = _normalize_price_to_prob(b.orderbook.best_yes_price)
        b_no = _normalize_price_to_prob(b.orderbook.best_no_price)

        # Case 1: Buy YES in A + Buy NO in B
        if a_yes is not None and b_no is not None:
            cost = a_yes + b_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(a.orderbook.best_yes_size or 0), float(b.orderbook.best_no_size or 0))
            if edge >= min_edge and exe >= config.min_executable_size:
                opps.append(
                    Opportunity(
                        question=a.market.question,
                        outcomes=tuple(a.market.outcomes),
                        buy_yes_venue=a.market.venue,
                        buy_yes_price=a_yes,
                        buy_no_venue=b.market.venue,
                        buy_no_price=b_no,
                        sum_price=cost,
                        executable_size=exe,
                        edge=edge,
                    )
                )

        # Case 2: Buy YES in B + Buy NO in A
        if b_yes is not None and a_no is not None:
            cost = b_yes + a_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(b.orderbook.best_yes_size or 0), float(a.orderbook.best_no_size or 0))
            if edge >= min_edge and exe >= config.min_executable_size:
                opps.append(
                    Opportunity(
                        question=a.market.question,
                        outcomes=tuple(a.market.outcomes),
                        buy_yes_venue=b.market.venue,
                        buy_yes_price=b_yes,
                        buy_no_venue=a.market.venue,
                        buy_no_price=a_no,
                        sum_price=cost,
                        executable_size=exe,
                        edge=edge,
                    )
                )

    opps.sort(key=lambda o: o.edge, reverse=True)
    return opps


def format_opportunity_table(opps: list[Opportunity], limit: int = 20) -> str:
    if not opps:
        return "No opportunities found."

    rows = opps[:limit]
    lines: list[str] = []
    lines.append("EDGE | SUM | EXEC | BUY YES (venue@price) | BUY NO (venue@price) | QUESTION")
    lines.append("-" * 110)
    for o in rows:
        yes_part = f"{o.buy_yes_venue}@{_fmt_float(o.buy_yes_price, 6)}"
        no_part = f"{o.buy_no_venue}@{_fmt_float(o.buy_no_price, 6)}"
        lines.append(
            f"{_fmt_float(o.edge, 6):<9} | "
            f"{_fmt_float(o.sum_price, 6):<7} | "
            f"{_fmt_float(o.executable_size, 2):<6} | "
            f"{yes_part:<22} | {no_part:<22} | {o.question}"
        )
    return "\n".join(lines)


def format_near_miss_pairs_table(
    snapshots_a: list[MarketSnapshot],
    snapshots_b: list[MarketSnapshot],
    config: ScannerConfig,
    limit: int = 20,
) -> str:
    """
    Near-miss ranking.

    - Intra-market (solo Kalshi): por defecto, solo consideramos "binarios normales" cuando
      yes_ask + no_ask ~ 1.0. En LAB podemos incluir también sumas raras como observabilidad
      (flag=WEIRD_SUM), pero siguen siendo *no ejecutables* como arbitraje clásico.

    - Cross-venue (A+B): calculamos las dos direcciones y rankeamos por edge (puede ser negativo).
    """
    rows: list[dict] = []

    def _keep(edge: float, exe: float) -> bool:
        return edge >= config.near_miss_edge_floor and exe >= config.min_executable_size

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

            normal_like = 0.90 <= cost <= 1.10
            if not normal_like and not config.near_miss_include_weird_sums:
                continue

            flag = "OK" if normal_like else "WEIRD_SUM"
            if not _keep(edge, exe):
                continue

            rows.append(
                {
                    "market_id": s.market.market_id,
                    "yes_ask": y,
                    "no_ask": n,
                    "sum_price": cost,
                    "edge": edge,
                    "executable_size": exe,
                    "flag": flag,
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
                exe = min(float(a.orderbook.best_yes_size or 0), float(b.orderbook.best_no_size or 0))
                if _keep(edge, exe):
                    rows.append(
                        {
                            "market_id": f"{a.market.venue}:{a.market.market_id} | {b.market.venue}:{b.market.market_id}",
                            "yes_ask": a_yes,
                            "no_ask": b_no,
                            "sum_price": cost,
                            "edge": edge,
                            "executable_size": exe,
                            "flag": "OK",
                        }
                    )

            # B yes + A no
            if b_yes is not None and a_no is not None:
                cost = b_yes + a_no
                edge = 1.0 - cost - _fee_buffer(cost, config)
                exe = min(float(b.orderbook.best_yes_size or 0), float(a.orderbook.best_no_size or 0))
                if _keep(edge, exe):
                    rows.append(
                        {
                            "market_id": f"{b.market.venue}:{b.market.market_id} | {a.market.venue}:{a.market.market_id}",
                            "yes_ask": b_yes,
                            "no_ask": a_no,
                            "sum_price": cost,
                            "edge": edge,
                            "executable_size": exe,
                            "flag": "OK",
                        }
                    )

    if not rows:
        return ""

    rows.sort(key=lambda r: r["edge"], reverse=True)
    rows = rows[:limit]

    lines: list[str] = []
    lines.append("MARKET_ID | YES_ASK | NO_ASK | SUM | EDGE | EXEC | FLAG")
    lines.append("-" * 120)
    for r in rows:
        lines.append(
            f"{r['market_id']} | "
            f"{_fmt_float(r['yes_ask'], 6)} | "
            f"{_fmt_float(r['no_ask'], 6)} | "
            f"{_fmt_float(r['sum_price'], 6)} | "
            f"{_fmt_float(r['edge'], 6)} | "
            f"{_fmt_float(r['executable_size'], 2)} | "
            f"{r['flag']}"
        )
    return "\n".join(lines)
