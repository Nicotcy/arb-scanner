from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import quote

import requests


@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class BookSummary:
    best_ask: Optional[BookLevel]


class PolymarketPublicClient:
    """
    Cliente read-only para:
      - Gamma API: descubrir markets/tokens
      - CLOB API: order book

    Filosofía anti-caos:
      - NO filtramos por active/closed aquí. Eso era una fuente enorme de "missing_tokens".
      - Resolvemos tokens aunque el market esté cerrado. Si luego el book está vacío, lo verás como noprices.
      - Damos errores explícitos en el debug/test (sin tragarnos excepciones silenciosamente).
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "arb-scanner/1.0 (read-only)",
                "Accept": "application/json",
            }
        )

    # ---------- HTTP helpers ----------

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------- Gamma (markets) ----------

    def gamma_get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        """
        Intenta varias estrategias:
          1) /markets?slug=...
          2) /markets?search=... y elegir exact match por slug
        Devuelve dict market o None.
        """
        base = "https://gamma-api.polymarket.com/markets"

        # 1) slug exact
        try:
            data = self._get_json(base, params={"slug": slug, "limit": 10, "offset": 0})
            market = self._pick_market_from_response(data, slug)
            if market:
                return market
        except Exception:
            pass

        # 2) search fallback
        try:
            data = self._get_json(base, params={"search": slug, "limit": 50, "offset": 0})
            market = self._pick_market_from_response(data, slug)
            if market:
                return market
        except Exception:
            pass

        return None

    def _pick_market_from_response(self, data: Any, slug: str) -> dict[str, Any] | None:
        """
        Gamma a veces devuelve list directamente o envuelve en dict (depende de endpoint/versión).
        Intentamos manejar ambos.
        """
        candidates: list[dict[str, Any]] = []
        if isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            # posibles claves típicas
            for k in ("markets", "data", "results"):
                if isinstance(data.get(k), list):
                    candidates = [x for x in data[k] if isinstance(x, dict)]
                    break
            if not candidates:
                # a veces el dict ya es el market
                if data.get("slug") == slug:
                    return data

        # exact match
        for m in candidates:
            if m.get("slug") == slug:
                return m

        # si no hay exact match, a veces slug viene dentro de la URL o parecido; devolvemos el más cercano
        if candidates:
            return candidates[0]

        return None

    def resolve_slug_to_yes_no_token_ids(self, slug: str) -> tuple[str, str]:
        """
        Devuelve (yes_token_id, no_token_id).
        Si no se puede resolver, levanta ValueError con motivo claro.
        """
        market = self.gamma_get_market_by_slug(slug)
        if not market:
            raise ValueError(f"Gamma: no encuentro market para slug='{slug}'")

        # outcomes puede venir como JSON string o como lista
        outcomes = market.get("outcomes")
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = None

        if not isinstance(outcomes, list) or not outcomes:
            raise ValueError(f"Gamma: market slug='{slug}' no trae outcomes parseables")

        # Buscar YES/NO
        yes = None
        no = None

        for o in outcomes:
            if not isinstance(o, dict):
                continue
            name = str(o.get("name") or o.get("outcome") or "").strip().upper()
            tok = o.get("token_id") or o.get("tokenId") or o.get("clobTokenId") or o.get("id")
            if not tok:
                continue

            if name == "YES":
                yes = str(tok)
            elif name == "NO":
                no = str(tok)

        if not yes or not no:
            # Si Gamma no etiqueta claramente, intentamos por orden (2 outcomes)
            if len(outcomes) == 2:
                a = outcomes[0]
                b = outcomes[1]
                ta = a.get("token_id") or a.get("tokenId") or a.get("clobTokenId") or a.get("id")
                tb = b.get("token_id") or b.get("tokenId") or b.get("clobTokenId") or b.get("id")
                if ta and tb:
                    # asumimos outcomes[0]=YES outcomes[1]=NO si no hay nombres
                    yes = str(ta)
                    no = str(tb)

        if not yes or not no:
            raise ValueError(f"Gamma: no pude extraer token_ids YES/NO para slug='{slug}'")

        return yes, no

    # ---------- CLOB (book) ----------

    def get_order_book_summary(self, token_id: str) -> BookSummary:
        """
        Usa /book del CLOB (public).
        Nos quedamos con best ask (si existe).
        """
        base = "https://clob.polymarket.com/book"
        data = self._get_json(base, params={"token_id": token_id})

        asks = data.get("asks") if isinstance(data, dict) else None
        best = None

        if isinstance(asks, list) and asks:
            # cada ask suele ser dict con price/size como strings
            top = asks[0]
            if isinstance(top, dict) and top.get("price") is not None and top.get("size") is not None:
                try:
                    best = BookLevel(price=float(top["price"]), size=float(top["size"]))
                except Exception:
                    best = None

        return BookSummary(best_ask=best)
