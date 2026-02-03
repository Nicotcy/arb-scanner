from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


# Whitelist manual de mappings cross-venue
# SOLO mercados que tú validas como semánticamente idénticos
MANUAL_MAPPINGS: List[MarketMapping] = [
    # Ejemplos históricos / placeholder (puedes borrarlos si quieres)
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-LK",
        polymarket_slug="will-trump-nominate-larry-kudlow-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-BPUL",
        polymarket_slug="will-trump-nominate-bill-pulte-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-AL",
        polymarket_slug="will-trump-nominate-arthur-laffer-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-HLUT",
        polymarket_slug="will-trump-nominate-howard-lutnick-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-DMAL",
        polymarket_slug="will-trump-nominate-david-malpass-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-RP",
        polymarket_slug="will-trump-nominate-ron-paul-as-the-next-fed-chair",
    ),
]


def load_manual_mappings(mode: str | None = None) -> list[MarketMapping]:
    """
    Devuelve los mappings manuales.
    El parámetro `mode` existe solo por compatibilidad con scanner/daemon.
    """
    return list(MANUAL_MAPPINGS)
