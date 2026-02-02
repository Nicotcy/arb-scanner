from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from arb_scanner.config import ScannerConfig
from arb_scanner.mappings import MarketMapping
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
    if price is None:
        return None
    p = float(price)
    if p > 1.0:
        return p / 100.0
    return p


def _fee_buffer(cost: float, config: ScannerConfig) -> float:
    return cost * (config.fee_buffer_bps / 10_000.0)


def _min_edge_for_opportunities(config: ScannerConfig) -> float:
    if config.alert_only:
        return config.alert_threshold
    return config.min_edge_opportunity


def compute_opportunities(
    snapshots_a: Iterable[MarketSnapshot],
    snapshots_b: Iterable[MarketSnapshot],
    config: ScannerConfig,
) -> list[Opportunity]:
    opps: list[Opportunity] = []
    min_edge = _min_edge_for_opportunities(config)

    for a, b in iter_pairs(snapshots_a, snapshots_b):
        if not a.market.is_binary or not b.market.is_binary:
            continue

        a_yes = _normalize_price_to_prob(a.orderbook.best_yes_price)
        a_no = _normalize_price_to_prob(a.orderbook.best_no_price)
        b_yes = _normalize_price_to_prob(b.orderbook.best_yes_price)
        b_no = _normalize_price_to_prob(b.orderbook.best_no_price)

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


def _index_by_market_id(snapshots: Iterable[MarketSnapshot]) -> dict[str, MarketSnapshot]:
    return {s.market.market_id: s for s in snapshots}


def compute_opportunities_from_mapping_pairs(
    kalshi_snaps: list[MarketSnapshot],
    poly_snaps: list[MarketSnapshot],
    mappings: list[MarketMapping],
    config: ScannerConfig,
) -> list[Opportunity]:
    """
    Compute cross-venue opportunities using explicit mapping pairs:
    kalshi market_id == kalshi_ticker
    polymarket market_id == polymarket_slug
    """
    k_idx = _index_by_market_id(kalshi_snaps)
    p_idx = _index_by_market_id(poly_snaps)

    opps: list[Opportunity] = []
    min_edge = _min_edge_for_opportunities(config)

    for mp in mappings:
        k = k_idx.get(mp.kalshi_ticker)
        p = p_idx.get(mp.polymarket_slug)
        if not k or not p:
            continue
        if not k.market.is_binary or not p.market.is_binary:
            continue

        k_yes = _normalize_price_to_prob(k.orderbook.best_yes_price)
        k_no = _normalize_price_to_prob(k.orderbook.best_no_price)
        p_yes = _normalize_price_to_prob(p.orderbook.best_yes_price)
        p_no = _normalize_price_to_prob(p.orderbook.best_no_price)

        # Direction 1: buy YES on Kalshi + buy NO on Polymarket
        if k_yes is not None and p_no is not None:
            cost = k_yes + p_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(k.orderbook.best_yes_size or 0), float(p.orderbook.best_no_size or 0))
            if edge >= min_edge and exe >= config.min_executable_size:
                opps.append(
                    Opportunity(
                        question=f"{k.market.market_id} ↔ {p.market.market_id}",
                        outcomes=("YES", "NO"),
                        buy_yes_venue=k.market.venue,
                        buy_yes_price=k_yes,
                        buy_no_venue=p.market.venue,
                        buy_no_price=p_no,
                        sum_price=cost,
                        executable_size=exe,
                        edge=edge,
                    )
                )

        # Direction 2: buy YES on Polymarket + buy NO on Kalshi
        if p_yes is not None and k_no is not None:
            cost = p_yes + k_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(p.orderbook.best_yes_size or 0), float(k.orderbook.best_no_size or 0))
            if edge >= min_edge and exe >= config.min_executable_size:
                opps.append(
                    Opportunity(
                        question=f"{k.market.market_id} ↔ {p.market.market_id}",
                        outcomes=("YES", "NO"),
                        buy_yes_venue=p.market.venue,
                        buy_yes_price=p_yes,
                        buy_no_venue=k.market.venue,
                        buy_no_price=k_no,
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
        yes_part = f"{o.buy_yes_venue}@{o.buy_yes_price:.6f}"
        no_part = f"{o.buy_no_venue}@{o.buy_no_price:.6f}"
        lines.append(
            f"{o.edge:.6f:<9} | "
            f"{o.sum_price:.6f:<7} | "
            f"{o.executable_size:.2f:<6} | "
            f"{yes_part:<22} | {no_part:<22} | {o.question}"
        )
    return "\n".join(lines)


def format_near_miss_pairs_table(
    snapshots_a: list[MarketSnapshot],
    snapshots_b: list[MarketSnapshot],
    config: ScannerConfig,
    limit: int = 20,
) -> str:
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
        # Cross-venue near-miss by question pairing
        for a, b in iter_pairs(snapshots_a, snapshots_b):
            if not a.market.is_binary or not b.market.is_binary:
                continue

            a_yes = _normalize_price_to_prob(a.orderbook.best_yes_price)
            a_no = _normalize_price_to_prob(a.orderbook.best_no_price)
            b_yes = _normalize_price_to_prob(b.orderbook.best_yes_price)
            b_no = _normalize_price_to_prob(b.orderbook.best_no_price)

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
            f"{r['yes_ask']:.6f} | "
            f"{r['no_ask']:.6f} | "
            f"{r['sum_price']:.6f} | "
            f"{r['edge']:.6f} | "
            f"{r['executable_size']:.2f} | "
            f"{r['flag']}"
        )
    return "\n".join(lines)


def format_near_miss_pairs_table_from_mapping_pairs(
    kalshi_snaps: list[MarketSnapshot],
    poly_snaps: list[MarketSnapshot],
    mappings: list[MarketMapping],
    config: ScannerConfig,
    limit: int = 20,
) -> str:
    k_idx = _index_by_market_id(kalshi_snaps)
    p_idx = _index_by_market_id(poly_snaps)

    rows: list[dict] = []

    def _keep(edge: float, exe: float) -> bool:
        return edge >= config.near_miss_edge_floor and exe >= config.min_executable_size

    for mp in mappings:
        k = k_idx.get(mp.kalshi_ticker)
        p = p_idx.get(mp.polymarket_slug)
        if not k or not p:
            continue
        if not k.market.is_binary or not p.market.is_binary:
            continue

        k_yes = _normalize_price_to_prob(k.orderbook.best_yes_price)
        k_no = _normalize_price_to_prob(k.orderbook.best_no_price)
        p_yes = _normalize_price_to_prob(p.orderbook.best_yes_price)
        p_no = _normalize_price_to_prob(p.orderbook.best_no_price)

        # k_yes + p_no
        if k_yes is not None and p_no is not None:
            cost = k_yes + p_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(k.orderbook.best_yes_size or 0), float(p.orderbook.best_no_size or 0))
            if _keep(edge, exe):
                rows.append(
                    {
                        "market_id": f"Kalshi:{k.market.market_id} | Poly:{p.market.market_id}",
                        "yes_ask": k_yes,
                        "no_ask": p_no,
                        "sum_price": cost,
                        "edge": edge,
                        "executable_size": exe,
                        "flag": "OK",
                    }
                )

        # p_yes + k_no
        if p_yes is not None and k_no is not None:
            cost = p_yes + k_no
            edge = 1.0 - cost - _fee_buffer(cost, config)
            exe = min(float(p.orderbook.best_yes_size or 0), float(k.orderbook.best_no_size or 0))
            if _keep(edge, exe):
                rows.append(
                    {
                        "market_id": f"Poly:{p.market.market_id} | Kalshi:{k.market.market_id}",
                        "yes_ask": p_yes,
                        "no_ask": k_no,
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
            f"{r['yes_ask']:.6f} | "
            f"{r['no_ask']:.6f} | "
            f"{r['sum_price']:.6f} | "
            f"{r['edge']:.6f} | "
            f"{r['executable_size']:.2f} | "
            f"{r['flag']}"
        )
    return "\n".join(lines)
