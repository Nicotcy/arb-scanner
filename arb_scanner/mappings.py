from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


# Whitelist cross-venue.
# IMPORTANTE:
# - Estos mappings NO son "SAFE definitivo", son válidos para bootstrap (LAB).
# - Todos son 1:1 por texto y sirven para probar el pipeline cross_venue.
MANUAL_MAPPINGS: list[MarketMapping] = [
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
        kalshi_ticker="KXFEDCHAIRNOM-29-RP",
        polymarket_slug="will-trump-nominate-ron-paul-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-HLUT",
        polymarket_slug="will-trump-nominate-howard-lutnick-as-the-next-fed-chair",
    ),
    MarketMapping(
        kalshi_ticker="KXFEDCHAIRNOM-29-DMAL",
        polymarket_slug="will-trump-nominate-david-malpass-as-the-next-fed-chair",
    ),
]


def load_manual_mappings() -> list[MarketMapping]:
    return list(MANUAL_MAPPINGS)
