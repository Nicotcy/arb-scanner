from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


# Fallback hardcodeado (por si NO existe .data/mappings.json)
MANUAL_MAPPINGS: List[MarketMapping] = [
    # Puedes dejarlo vacío si quieres
]


def _parse_mapping_item(x: dict) -> MarketMapping:
    return MarketMapping(
        kalshi_ticker=str(x["kalshi_ticker"]),
        polymarket_slug=str(x["polymarket_slug"]),
        polymarket_yes_token_id=(str(x["polymarket_yes_token_id"]) if x.get("polymarket_yes_token_id") else None),
        polymarket_no_token_id=(str(x["polymarket_no_token_id"]) if x.get("polymarket_no_token_id") else None),
    )


def load_manual_mappings(mode: str | None = None) -> list[MarketMapping]:
    """
    Fuente de mappings cross-venue.

    Prioridad:
      1) .data/mappings.json (si existe)
      2) MANUAL_MAPPINGS (fallback)
    """
    path = os.environ.get("ARB_MAPPINGS_PATH", ".data/mappings.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            raise ValueError(f"{path} debe ser una lista JSON de mappings")
        return [_parse_mapping_item(item) for item in raw]

    return list(MANUAL_MAPPINGS)
