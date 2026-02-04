from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass
class BookLevel:
    price: float
    size: float


@dataclass
class BookSummary:
    best_ask: Optional[BookLevel]


class PolymarketPublicClient:
    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "arb-scanner/1.0 (read-only)", "Accept": "application/json"}
        )

    def _normalize_json(self, data: Any) -> Any:
        if isinstance(data, str):
            s = data.strip()
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    return json.loads(s)
                except Exception:
                    return data
        return data

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        r = self.session.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            return r.text
        return self._normalize_json(data)

    def gamma_get_market_by_slug(self, slug: str) -> dict[str, Any] | None:
        base = "https://gamma-api.polymarket.com/markets"
        for params in (
            {"slug": slug, "limit": 10, "offset": 0},
            {"search": slug, "limit": 50, "offset": 0},
        ):
            try:
                data = self._get_json(base, params=params)
                market = self._pick_market_from_response(data, slug)
                if market:
                    return market
            except Exception:
                continue
        return None

    def _pick_market_from_response(self, data: Any, slug: str) -> dict[str, Any] | None:
        data = self._normalize_json(data)

        if isinstance(data, dict) and data.get("slug") == slug:
            return data

        candidates: list[dict[str, Any]] = []
        if isinstance(data, list):
            candidates = [x for x in data if isinstance(x, dict)]
        elif isinstance(data, dict):
            for k in ("markets", "data", "results"):
                v = self._normalize_json(data.get(k))
                if isinstance(v, list):
                    candidates = [x for x in v if isinstance(x, dict)]
                    break
        else:
            return None

        for m in candidates:
            if m.get("slug") == slug:
                return m
        return candidates[0] if candidates else None

    def resolve_slug_to_yes_no_token_ids(self, slug: str) -> tuple[str, str]:
        market = self.gamma_get_market_by_slug(slug)
        if not market:
            raise ValueError(f"Gamma: no encuentro market para slug='{slug}'")

        outcomes = self._normalize_json(market.get("outcomes"))
        clob_ids = self._normalize_json(market.get("clobTokenIds"))

        # FORMATO REAL: outcomes list[str] + clobTokenIds list[str]
        if isinstance(outcomes, list) and isinstance(clob_ids, list) and len(outcomes) >= 2 and len(outcomes) == len(clob_ids):
            name_to_id: dict[str, str] = {}
            for name, tid in zip(outcomes, clob_ids):
                if name is None or tid is None:
                    continue
                name_to_id[str(name).strip().upper()] = str(tid)

            y = name_to_id.get("YES")
            n = name_to_id.get("NO")
            if y and n:
                return y, n

            # fallback por orden típico Yes/No
            return str(clob_ids[0]), str(clob_ids[1])

        # FORMATO ANTIGUO: outcomes list[dict]
        def pick_tok(d: dict[str, Any]) -> str | None:
            return d.get("token_id") or d.get("tokenId") or d.get("clobTokenId") or d.get("id")

        outcomes2 = self._normalize_json(market.get("outcomes"))
        if isinstance(outcomes2, str):
            try:
                outcomes2 = json.loads(outcomes2)
            except Exception:
                outcomes2 = None

        if isinstance(outcomes2, list) and outcomes2 and all(isinstance(x, dict) for x in outcomes2):
            yes = no = None
            for o in outcomes2:
                name = str(o.get("name") or o.get("outcome") or "").strip().upper()
                tok = pick_tok(o)
                if not tok:
                    continue
                if name == "YES":
                    yes = str(tok)
                elif name == "NO":
                    no = str(tok)
            if yes and no:
                return yes, no
            if len(outcomes2) == 2:
                ta = pick_tok(outcomes2[0])
                tb = pick_tok(outcomes2[1])
                if ta and tb:
                    return str(ta), str(tb)

        raise ValueError(f"Gamma: no pude extraer token_ids YES/NO para slug='{slug}'")

    def get_order_book_summary(self, token_id: str) -> BookSummary:
        url = "https://clob.polymarket.com/book"
        data = self._get_json(url, params={"token_id": token_id})
        data = self._normalize_json(data)

        if not isinstance(data, dict):
            raise ValueError(f"CLOB /book: respuesta no-dict token_id={token_id!r}: {type(data).__name__}")

        asks = self._normalize_json(data.get("asks"))
        best = None
        if isinstance(asks, list) and asks:
            top = asks[0]
            if isinstance(top, dict) and top.get("price") is not None and top.get("size") is not None:
                try:
                    best = BookLevel(price=float(top["price"]), size=float(top["size"]))
                except Exception:
                    best = None

        return BookSummary(best_ask=best)
