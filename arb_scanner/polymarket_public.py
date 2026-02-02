from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBookSummary:
    token_id: str
    best_bid: BookLevel | None
    best_ask: BookLevel | None


class PolymarketPublicClient:
    """
    Read-only client for:
    - CLOB orderbook: GET /book?token_id=...
    - Gamma markets metadata: GET /markets?... (for clobTokenIds)

    Docs:
    - CLOB GET /book with query param token_id (required) :contentReference[oaicite:0]{index=0}
    - Gamma /markets for metadata including clobTokenIds :contentReference[oaicite:1]{index=1}
    - Quickstart example shows clobTokenIds=[YES,NO] :contentReference[oaicite:2]{index=2}
    """

    def __init__(self, timeout_s: float = 15.0, retry_429: int = 3) -> None:
        self.timeout_s = timeout_s
        self.retry_429 = retry_429

    def _get_json(self, url: str) -> Any:
        last_err: Exception | None = None
        for attempt in range(self.retry_429 + 1):
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read().decode("utf-8")

                if status == 429:
                    # backoff simple
                    time.sleep(0.5 * (attempt + 1))
                    continue

                return json.loads(body)
            except Exception as e:
                last_err = e
                time.sleep(0.2 * (attempt + 1))
        raise RuntimeError(f"GET failed: {url} err={last_err}")

    def get_order_book_summary(self, token_id: str) -> OrderBookSummary:
        """
        CLOB orderbook summary.
        Endpoint: GET https://clob.polymarket.com/book?token_id=... :contentReference[oaicite:3]{index=3}
        """
        q = urllib.parse.urlencode({"token_id": token_id})
        url = f"{CLOB_HOST}/book?{q}"
        data = self._get_json(url)

        bids = data.get("bids") or []
        asks = data.get("asks") or []

        def _parse_level(level: dict) -> BookLevel | None:
            try:
                return BookLevel(price=float(level["price"]), size=float(level["size"]))
            except Exception:
                return None

        best_bid = _parse_level(bids[0]) if bids else None
        best_ask = _parse_level(asks[0]) if asks else None

        return OrderBookSummary(token_id=token_id, best_bid=best_bid, best_ask=best_ask)

    def gamma_get_markets_by_slug(self, slug: str) -> list[dict]:
        """
        Gamma markets endpoint supports filtering by slug. :contentReference[oaicite:4]{index=4}
        We'll call: /markets?slug=<slug>
        """
        q = urllib.parse.urlencode({"slug": slug})
        url = f"{GAMMA_HOST}/markets?{q}"
        data = self._get_json(url)
        if isinstance(data, list):
            return data
        return []

    @staticmethod
    def _parse_clob_token_ids(value: Any) -> list[str]:
        """
        Gamma sometimes returns clobTokenIds as:
        - list[str]
        - stringified JSON
        - comma-separated string (rare)
        """
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str):
            s = value.strip()
            # try JSON list first
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:
                pass
            # fallback comma-separated
            if "," in s:
                return [p.strip() for p in s.split(",") if p.strip()]
            return [s]
        return []

    def resolve_slug_to_yes_no_token_ids(self, slug: str) -> tuple[str, str] | None:
        """
        Resolve Polymarket market slug -> (YES_token_id, NO_token_id) using Gamma.
        Quickstart examples show clobTokenIds=[YES, NO] for binary markets. :contentReference[oaicite:5]{index=5}
        """
        markets = self.gamma_get_markets_by_slug(slug)
        if not markets:
            return None

        # pick first match
        m = markets[0]
        token_ids = self._parse_clob_token_ids(m.get("clobTokenIds"))

        if len(token_ids) < 2:
            return None

        # Convention: [YES, NO]
        return (token_ids[0], token_ids[1])
