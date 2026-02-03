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
