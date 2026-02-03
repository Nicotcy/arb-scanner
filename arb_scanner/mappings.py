from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


# Mantén esto como tu "whitelist" cross-venue.
# Regla: solo pares que tú hayas validado como equivalentes.
MANUAL_MAPPINGS: list[MarketMapping] = [
    # Ejemplo (este es malo para arbitraje, pero sirve como prueba técnica)
    MarketMapping(
        kalshi_ticker="KXSB-26-SEA",
        polymarket_slug="will-the-seattle-seahawks-win-super-bowl-2026",
    ),

    # Añade aquí más, por ejemplo:
    # MarketMapping(kalshi_ticker="KXXXX-...", polymarket_slug="some-polymarket-slug"),
]


def load_manual_mappings() -> list[MarketMapping]:
    return list(MANUAL_MAPPINGS)
