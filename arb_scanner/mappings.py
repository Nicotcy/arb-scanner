# arb_scanner/mappings.py

import json
import os
from typing import List, Optional

# ... aquí arriba ya tienes MarketMapping definido

def load_manual_mappings(mode: str | None = None, path: str = ".data/mappings.json") -> list["MarketMapping"]:
    """
    Load manual mappings from JSON file if present.
    Fallback to built-in defaults only if file is missing.
    """

    if os.path.exists(path):
        raw = json.load(open(path, "r"))
        out: list[MarketMapping] = []
        for x in raw:
            out.append(MarketMapping(
                kalshi_ticker=x.get("kalshi_ticker"),
                polymarket_slug=x.get("polymarket_slug"),
                polymarket_yes_token_id=x.get("polymarket_yes_token_id"),
                polymarket_no_token_id=x.get("polymarket_no_token_id"),
            ))
        return out

    # --- Fallback: antiguos defaults internos (lo que tengas ahora) ---
    # deja aquí el código que ya tenías para mode->defaults
    # por ejemplo: return DEFAULTS_BY_MODE[mode] ...
    return _load_builtin_defaults(mode)

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class MarketMapping:
    kalshi_ticker: str
    polymarket_slug: str
    polymarket_yes_token_id: str | None = None
    polymarket_no_token_id: str | None = None


def _coerce_mapping(obj: Any) -> MarketMapping:
    # Acepta dicts (lo más probable) o ya-dataclasses
    if isinstance(obj, MarketMapping):
        return obj
    if not isinstance(obj, dict):
        raise TypeError(f"Mapping inválido (no dict): {type(obj)}")

    return MarketMapping(
        kalshi_ticker=str(obj.get("kalshi_ticker") or ""),
        polymarket_slug=str(obj.get("polymarket_slug") or ""),
        polymarket_yes_token_id=(None if obj.get("polymarket_yes_token_id") in ("", None) else str(obj.get("polymarket_yes_token_id"))),
        polymarket_no_token_id=(None if obj.get("polymarket_no_token_id") in ("", None) else str(obj.get("polymarket_no_token_id"))),
    )


# Si ya existe load_manual_mappings arriba, la envolvemos.
# Si no existe, definimos una básica.
try:
    load_manual_mappings  # type: ignore[name-defined]
except NameError:
    def load_manual_mappings(path: str, mode: str | None = None) -> list[MarketMapping]:
        raw = json.load(open(path))
        if not isinstance(raw, list):
            raise ValueError("mappings.json debe ser una lista")
        out = [_coerce_mapping(x) for x in raw]
        # filtro mínimo por sanidad
        out = [m for m in out if m.kalshi_ticker and m.polymarket_slug]
        return out
else:
    _orig_load_manual_mappings = load_manual_mappings  # type: ignore[assignment]

    def load_manual_mappings(path: str, mode: str | None = None) -> list[MarketMapping]:
        raw = _orig_load_manual_mappings(path, mode=mode)  # puede devolver list[dict] o list[...]
        out = [_coerce_mapping(x) for x in raw]
        out = [m for m in out if m.kalshi_ticker and m.polymarket_slug]
        return out
