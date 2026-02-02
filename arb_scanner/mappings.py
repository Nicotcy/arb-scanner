from arb_scanner.mappings import MarketMapping

def load_manual_mappings() -> list[MarketMapping]:
    return [
        MarketMapping(
            kalshi_ticker="KXSB-26-NE",
            polymarket_slug="super-bowl-champion-2026-731-will-the-seattle-seahawks-win-super-bowl-2026",
        ),
    ]
