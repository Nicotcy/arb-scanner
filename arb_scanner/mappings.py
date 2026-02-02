from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketMapping:
    """
    Mapping explícito de un mercado binario equivalente entre venues.

    kalshi_ticker:
      - ticker tradeable de Kalshi (leg ticker si viene de MVE).
    polymarket_slug:
      - por ahora un identificador humano (slug o texto corto).
      - cuando implementemos Polymarket real, lo cambiaremos a condition_id/token_id.
    """
    kalshi_ticker: str
    polymarket_slug: str


def load_manual_mappings() -> list[MarketMapping]:
    """
    Añade aquí tus pares 100% equivalentes.

    Reglas para que sea "seguro":
      - eventos con resolución objetiva (elecciones, datos oficiales, fechas, macro)
      - evitar deportes y props (lesiones, anulaciones, reglas distintas)
      - evitar mercados con posibilidad de void/cancel diferente entre plataformas
    """
    return [
        # Ejemplo de formato (BORRA el # cuando tengas uno real):
        # MarketMapping(kalshi_ticker="KXUSPR2028-TRUMP", polymarket_slug="will-donald-trump-win-2028"),
    ]
