from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Any

import json
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
    - En tu entorno, CLOB (/book, /price) devuelve 404 siempre.
    - Gamma sí responde y trae campos suficientes para un precio indicativo.

    Precio (orden de preferencia):
      1) outcomePrices (si viene, incluso si viene stringificado)
      2) bestAsk (YES) => NO = 1 - YES
      3) lastTradePrice (YES) => NO = 1 - YES

    Size:
      - No tenemos size real sin orderbook => size=0.0
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
            if data.get("slug") == slug:
                return data
            for k in ("markets", "data", "results"):
                v = data.get(k)
                if isinstance(v, list) and v:
                    for m in v:
                        if isinstance(m, dict) and m.get("slug") == slug:
                            return m
                    return v[0]

        return None

    def _as_float(self, x: Any) -> float | None:
        try:
            if x is None:
                return None
            return float(x)
        except Exception:
            return None

    def _extract_yes_no_prices(self, market: dict[str, Any]) -> tuple[float, float] | None:
        # 1) outcomePrices puede venir como lista o como string JSON
        outcomes = market.get("outcomes")
        prices = market.get("outcomePrices")

        if isinstance(prices, str):
            s = prices.strip()
            if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                try:
                    prices = json.loads(s)
                except Exception:
                    pass

        if isinstance(outcomes, str):
            s = outcomes.strip()
            if s.startswith("[") and s.endswith("]"):
                try:
                    outcomes = json.loads(s)
                except Exception:
                    pass

        # Caso A: outcomes=list y outcomePrices=list
        if isinstance(outcomes, list) and isinstance(prices, list) and len(outcomes) >= 2 and len(prices) == len(outcomes):
            # mapeo por nombre si podemos
            name_to_price: dict[str, float] = {}
            for name, p in zip(outcomes, prices):
                key = str(name).strip().upper()
                fp = self._as_float(p)
                if fp is not None:
                    name_to_price[key] = fp

            y = name_to_price.get("YES") or name_to_price.get("YES ")  # por si acaso
            n = name_to_price.get("NO")  or name_to_price.get("NO ")
            if y is not None and n is not None:
                return y, n

            # fallback por orden típico (Yes, No)
            y = self._as_float(prices[0])
            n = self._as_float(prices[1])
            if y is not None and n is not None:
                return y, n

        # Caso B: prices como dict (por si Gamma cambia)
        if isinstance(prices, dict):
            # intentamos claves típicas
            y = self._as_float(prices.get("YES") or prices.get("yes"))
            n = self._as_float(prices.get("NO") or prices.get("no"))
            if y is not None and n is not None:
                return y, n

        # 2) bestAsk como precio YES indicativo
        best_ask = self._as_float(market.get("bestAsk"))
        if best_ask is not None:
            yes = best_ask
            no = 1.0 - yes
            if 0.0 <= yes <= 1.0 and 0.0 <= no <= 1.0:
                return yes, no

        # 3) lastTradePrice como precio YES indicativo
        last = self._as_float(market.get("lastTradePrice"))
        if last is not None:
            yes = last
            no = 1.0 - yes
            if 0.0 <= yes <= 1.0 and 0.0 <= no <= 1.0:
                return yes, no

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
                best_yes_size=0.0,
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
