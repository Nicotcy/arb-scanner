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


def compute_opportunities(
    a_snapshots: Sequence[MarketSnapshot],
    b_snapshots: Sequence[MarketSnapshot],
    min_edge: float = 0.0,
) -> list[Opportunity]:
    """
    Match conservador: por texto exacto de 'question' + outcomes.

    Arbitraje (binario Yes/No):
      - YES en A + NO en B si yes_ask(A) + no_ask(B) < 1
      - NO en A + YES en B si no_ask(A) + yes_ask(B) < 1

    edge = 1 - suma_asks
    """
    a_map: dict[tuple[str, tuple[str, ...]], MarketSnapshot] = {}
    for s in a_snapshots:
        key = (s.market.question, tuple(s.market.outcomes))
        a_map[key] = s

    opps: list[Opportunity] = []
    for b in b_snapshots:
        key = (b.market.question, tuple(b.market.outcomes))
        a = a_map.get(key)
        if not a:
            continue

        a_ob = a.orderbook
        b_ob = b.orderbook

        if a_ob.best_yes_price is None or a_ob.best_no_price is None:
            continue
        if b_ob.best_yes_price is None or b_ob.best_no_price is None:
            continue

        sum1 = float(a_ob.best_yes_price) + float(b_ob.best_no_price)
        edge1 = 1.0 - sum1
        if edge1 >= min_edge:
            opps.append(
                Opportunity(
                    question=a.market.question,
                    outcomes=a.market.outcomes,
                    buy_yes_venue=a.market.venue,
                    buy_yes_price=float(a_ob.best_yes_price),
                    buy_no_venue=b.market.venue,
                    buy_no_price=float(b_ob.best_no_price),
                    edge=edge1,
                )
            )

        sum2 = float(a_ob.best_no_price) + float(b_ob.best_yes_price)
        edge2 = 1.0 - sum2
        if edge2 >= min_edge:
            opps.append(
                Opportunity(
                    question=a.market.question,
                    outcomes=a.market.outcomes,
                    buy_yes_venue=b.market.venue,
                    buy_yes_price=float(b_ob.best_yes_price),
                    buy_no_venue=a.market.venue,
                    buy_no_price=float(a_ob.best_no_price),
                    edge=edge2,
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
