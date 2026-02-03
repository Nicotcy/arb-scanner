from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


# Two explicit buckets.
# SAFE should only contain pairs you've verified have aligned resolution rules.
# LAB can contain "looks equivalent" pairs you want to explore in paper.
SAFE_MAPPINGS: list[MarketMapping] = [
    # put SAFE pairs here
]

LAB_MAPPINGS: list[MarketMapping] = [
    # example bootstrap LAB (remove/replace as you validate):
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-LK", polymarket_slug="will-trump-nominate-larry-kudlow-as-the-next-fed-chair"),
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-BPUL", polymarket_slug="will-trump-nominate-bill-pulte-as-the-next-fed-chair"),
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-AL", polymarket_slug="will-trump-nominate-arthur-laffer-as-the-next-fed-chair"),
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-RP", polymarket_slug="will-trump-nominate-ron-paul-as-the-next-fed-chair"),
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-HLUT", polymarket_slug="will-trump-nominate-howard-lutnick-as-the-next-fed-chair"),
    MarketMapping(kalshi_ticker="KXFEDCHAIRNOM-29-DMAL", polymarket_slug="will-trump-nominate-david-malpass-as-the-next-fed-chair"),
]

# Backwards-compatible alias:
MANUAL_MAPPINGS: list[MarketMapping] = SAFE_MAPPINGS + LAB_MAPPINGS


def load_manual_mappings(mode: str | None = None) -> list[MarketMapping]:
    # mode: "safe" -> SAFE only, otherwise SAFE+LAB
    if mode == "safe":
        return list(SAFE_MAPPINGS)
    return list(MANUAL_MAPPINGS)
