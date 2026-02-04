from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Any

import requests

from arb_scanner.mappings import MarketMapping
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


@dataclass
class PolymarketStats:
    total_mappings: int = 0
    gamma_ok: int = 0
    gamma_not_found: int = 0
    gamma_errors: int = 0
    missing_prices: int = 0
    ok: int = 0


class PolymarketProvider(MarketDataProvider):
    """
    Polymarket provider (READ-ONLY) usando SOLO Gamma API.

    Por qué:
    - En tu entorno, los endpoints públicos del CLOB (/book, /price) devuelven 404 siempre.
    - Gamma sí responde y trae outcomePrices / bestAsk / question, suficiente para snapshots y cross-venue.

    Limitación consciente:
    - Esto NO es top-of-book real del CLOB. Lo tratamos como precio indicativo (size=0).
    """

    GAMMA_URL = "https://gamma-api.polymarket.com/markets"

    def __init__(self, mappings: list[MarketMapping]) -> None:
        self.mappings = list(mappings)
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "arb-scanner/1.0 (read-only)", "Accept": "application/json"}
        )
        self._question_cache: dict[str, str] = {}

    def name(self) -> str:
        return "Polymarket"

    def _gamma_get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        # Gamma suele devolver lista de markets
        r = self.session.get(
            self.GAMMA_URL,
            params={"slug": slug, "limit": 10, "offset": 0},
            timeout=20,
        )
        r.raise_for_status()
        data = r.json()

        if isinstance(data, list):
            for m in data:
                if isinstance(m, dict) and m.get("slug") == slug:
                    return m
            return data[0] if data else None

        if isinstance(data, dict):
            # por si la API cambia y devuelve dict
            if data.get("slug") == slug:
                return data
            for k in ("markets", "data", "results"):
                v = data.get(k)
                if isinstance(v, list) and v:
                    for m in v:
                        if isinstance(m, dict) and m.get("slug") == slug:
                            return m
                    return v[0] if v else None

        return None

    def _extract_yes_no_prices(self, market: dict[str, Any]) -> tuple[float, float] | None:
        """
        Preferimos outcomePrices porque es binario y directo.
        outcomes suele ser ["Yes","No"] y outcomePrices ["0.65","0.35"] (strings).
        """
        outcomes = market.get("outcomes")
        prices = market.get("outcomePrices")

        if isinstance(outcomes, list) and isinstance(prices, list) and len(outcomes) == len(prices) and len(prices) >= 2:
            # mapeo por nombre si existe
            name_to_price: dict[str, float] = {}
            for name, p in zip(outcomes, prices):
                if name is None or p is None:
                    continue
                try:
                    name_to_price[str(name).strip().upper()] = float(p)
                except Exception:
                    continue

            y = name_to_price.get("YES")
            n = name_to_price.get("NO")
            if y is not None and n is not None:
                return y, n

            # fallback por orden típico (Yes, No)
            try:
                return float(prices[0]), float(prices[1])
            except Exception:
                return None

        # fallback: a veces hay bestAsk (pero suele ser único / no por outcome)
        # Si bestAsk existe y spread existe, no podemos inferir NO de forma fiable → no lo usamos
        return None

    def _get_question_for_slug(self, slug: str, market: dict[str, Any] | None) -> str:
        if slug in self._question_cache:
            return self._question_cache[slug]
        q = None
        if isinstance(market, dict):
            q = market.get("question") or market.get("title") or market.get("name")
        if not q:
            q = slug
        q = str(q)
        self._question_cache[slug] = q
        return q

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        stats = PolymarketStats(total_mappings=len(self.mappings))

        for mp in self.mappings:
            slug = mp.polymarket_slug
            if not slug:
                stats.gamma_not_found += 1
                continue

            try:
                market_raw = self._gamma_get_market_by_slug(slug)
                if not market_raw:
                    stats.gamma_not_found += 1
                    continue
                stats.gamma_ok += 1
            except Exception:
                stats.gamma_errors += 1
                continue

            prices = self._extract_yes_no_prices(market_raw)
            if not prices:
                stats.missing_prices += 1
                continue

            yes_price, no_price = prices

            ob = OrderBookTop(
                best_yes_price=float(yes_price),
                best_yes_size=0.0,  # Gamma no es orderbook: size desconocido
                best_no_price=float(no_price),
                best_no_size=0.0,
            )

            market = Market(
                venue="Polymarket",
                market_id=slug,
                question=self._get_question_for_slug(slug, market_raw),
                outcomes=("YES", "NO"),
            )

            stats.ok += 1
            yield MarketSnapshot(market=market, orderbook=ob)

        print(
            "PolymarketProvider stats: "
            f"mappings={stats.total_mappings} ok={stats.ok} "
            f"gamma_ok={stats.gamma_ok} not_found={stats.gamma_not_found} "
            f"errors={stats.gamma_errors} missing_prices={stats.missing_prices}"
        )
