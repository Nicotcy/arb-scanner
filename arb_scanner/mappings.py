from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    """
    Mapping explícito de un mercado binario equivalente entre venues.
    - kalshi_ticker: ticker tradeable de Kalshi
    - polymarket_slug: identificador simple (por ahora) para Polymarket
      (luego lo convertimos a condition_id / token_id cuando integremos la API real)
    """
    kalshi_ticker: str
    polymarket_slug: str


def load_manual_mappings() -> list[MarketMapping]:
    """
    IMPORTANTÍSIMO: al principio, esto es manual y pequeño.
    Aquí vas añadiendo pares equivalentes que tú confirmes que son 100% comparables.
    """
    return [
        # Ejemplos (REEMPLAZA por los tuyos reales):
        # MarketMapping(kalshi_ticker="KXUSPres2028", polymarket_slug="will-trump-win-2028"),
    ]
