from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str

    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


def load_manual_mappings() -> list[MarketMapping]:
    return [
        MarketMapping(
            kalshi_ticker="KXSB-26-SEA",
            polymarket_slug="will-the-seattle-seahawks-win-super-bowl-2026",
        ),
    ]
