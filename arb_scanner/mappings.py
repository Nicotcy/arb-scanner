from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str

    # Optional: resolved from Gamma clobTokenIds (YES, NO)
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


def load_manual_mappings() -> list[MarketMapping]:
    """
    Add your mappings here. Start with a few, test, then expand.
    You can omit token_ids; the scanner will try to resolve them via Gamma.
    """
    return [
        # Example:
        # MarketMapping(
        #   kalshi_ticker="KX....",
        #   polymarket_slug="will-bitcoin-reach-100k-by-2025",
        # ),
    ]
