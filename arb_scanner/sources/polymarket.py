cat > arb_scanner/sources/polymarket.py <<'PY'
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
import time
import requests


# Snapshots “compatibles por atributos” con lo que usa daemon.py/scanner.py:
# - s.market.venue / market_id / question
# - s.orderbook.best_yes_price / best_no_price / best_yes_size / best_no_size

@dataclass
class Market:
    venue: str
    market_id: str
    question: str

@dataclass
class OrderBook:
    best_yes_price: Optional[float]
    best_no_price: Optional[float]
    best_yes_size: Optional[float]
    best_no_size: Optional[float]

@dataclass
class Snapshot:
    market: Market
    orderbook: OrderBook


class PolymarketProvider:
    """
    Read-only Polymarket provider using PUBLIC CLOB endpoints (no auth):
      - GET https://clob.polymarket.com/price?token_id=...&side=buy
      - GET https://clob.polymarket.com/book?token_id=...   (opcional, no hace falta para top-of-book)
    Docs: https://docs.polymarket.com/quickstart/fetching-data
    """

    CLOB_BASE = "https://clob.polymarket.com"
    GAMMA_BASE = "https://gamma-api.polymarket.com"

    def __init__(self, mappings: list):
        # mappings: lista de MarketMapping o dicts con:
        # - polymarket_slug
        # - polymarket_yes_token_id
        # - polymarket_no_token_id
        self.mappings = mappings
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": "arb-scanner/1.0 (read-only)"})

    def name(self) -> str:
        return "Polymarket"

    def _get_field(self, obj, key: str):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    def _gamma_question(self, slug: str) -> str:
        # Mejor esfuerzo: si falla, devolvemos el slug como “question”
        try:
            r = self.s.get(f"{self.GAMMA_BASE}/markets", params={"slug": slug}, timeout=15)
            r.raise_for_status()
            data = r.json()
            # gamma /markets?slug=... normalmente devuelve lista
            if isinstance(data, list) and data:
                q = data[0].get("question") or data[0].get("title") or slug
                return str(q)
            if isinstance(data, dict):
                q = data.get("question") or data.get("title") or slug
                return str(q)
        except Exception:
            pass
        return slug

    def _clob_buy_price(self, token_id: str) -> tuple[Optional[float], Optional[float]]:
        """
        Devuelve (price, size) para comprar (side=buy).
        Según docs, /price devuelve {"price":"0.65"}.
        El tamaño no lo da /price; si quieres size real, usar /book.
        """
        try:
            r = self.s.get(f"{self.CLOB_BASE}/price", params={"token_id": token_id, "side": "buy"}, timeout=15)
            r.raise_for_status()
            j = r.json()
            p = j.get("price")
            if p is None:
                return None, None
            return float(p), None
        except Exception:
            return None, None

    def _clob_best_ask_and_size(self, token_id: str) -> tuple[Optional[float], Optional[float]]:
        """
        Lee el book y extrae el mejor ask (lo que pagas para comprar) y su size.
        Si el book está vacío, devuelve (None, None).
        """
        try:
            r = self.s.get(f"{self.CLOB_BASE}/book", params={"token_id": token_id}, timeout=15)
            r.raise_for_status()
            j = r.json()
            asks = j.get("asks") or []
            if not asks:
                return None, None
            # formato esperado: [{"price":"0.66","size":"300"}, ...]
            best = asks[0]
            return float(best.get("price")), float(best.get("size")) if best.get("size") is not None else None
        except Exception:
            return None, None

    def fetch_market_snapshots(self) -> Iterable[Snapshot]:
        out: List[Snapshot] = []

        # cache simple para no machacar gamma si hay muchas iteraciones
        question_cache: dict[str, str] = {}

        for mp in self.mappings:
            slug = str(self._get_field(mp, "polymarket_slug"))
            yes_id = self._get_field(mp, "polymarket_yes_token_id")
            no_id = self._get_field(mp, "polymarket_no_token_id")

            if not slug or not yes_id or not no_id:
                continue

            yes_id = str(yes_id)
            no_id = str(no_id)

            # pregunta (texto)
            if slug not in question_cache:
                question_cache[slug] = self._gamma_question(slug)
            q = question_cache[slug]

            # Mejor ask real desde orderbook (si hay); si no hay, fallback a /price
            yes_ask, yes_sz = self._clob_best_ask_and_size(yes_id)
            no_ask, no_sz = self._clob_best_ask_and_size(no_id)

            if yes_ask is None:
                yes_ask, _ = self._clob_buy_price(yes_id)
            if no_ask is None:
                no_ask, _ = self._clob_buy_price(no_id)

            # Ojo: aquí estamos guardando “ask para comprar YES” y “ask para comprar NO”
            # El algoritmo luego hace sumas para arbitraje.
            snap = Snapshot(
                market=Market(venue="Polymarket", market_id=slug, question=q),
                orderbook=OrderBook(
                    best_yes_price=yes_ask,
                    best_no_price=no_ask,
                    best_yes_size=yes_sz,
                    best_no_size=no_sz,
                ),
            )
            out.append(snap)

        return out
PY
