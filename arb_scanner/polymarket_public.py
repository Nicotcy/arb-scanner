from __future__ import annotations

import json
import os
import ssl
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
      - Gamma: market metadata (slug -> market details including clobTokenIds)
      - CLOB: orderbook (token_id -> bids/asks)

    Notes:
      - Some environments hit SSL issues (CERTIFICATE_VERIFY_FAILED). We use certifi if installed.
      - Some environments hit 403 on Gamma without "browser-like" headers. We add them.
      - Gamma has a dedicated endpoint: GET /markets/slug/{slug} (preferred). :contentReference[oaicite:1]{index=1}
    """

    def __init__(self, timeout_s: float = 15.0, retry_429: int = 3) -> None:
        self.timeout_s = timeout_s
        self.retry_429 = retry_429

    def _ssl_context(self) -> ssl.SSLContext:
        if os.getenv("POLYMARKET_INSECURE_SSL", "0") == "1":
            return ssl._create_unverified_context()

        try:
            import certifi  # type: ignore

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()

    def _default_headers(self) -> dict[str, str]:
        # "Normal" browser-ish headers help avoid 403 from basic WAF rules
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://polymarket.com/",
            "Origin": "https://polymarket.com",
        }

    def _get_json(self, url: str) -> Any:
        last_err: Exception | None = None
        ctx = self._ssl_context()
        headers = self._default_headers()

        for attempt in range(self.retry_429 + 1):
            try:
                req = urllib.request.Request(url, method="GET", headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read().decode("utf-8")

                if status == 429:
                    time.sleep(0.6 * (attempt + 1))
                    continue

                return json.loads(body)

            except Exception as e:
                last_err = e
                time.sleep(0.25 * (attempt + 1))

        raise RuntimeError(f"GET failed: {url} err={last_err}")

    def get_order_book_summary(self, token_id: str) -> OrderBookSummary:
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

    @staticmethod
    def _parse_clob_token_ids(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(x) for x in value]
        if isinstance(value, str):
            s = value.strip()
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except Exception:
                pass
            if "," in s:
                return [p.strip() for p in s.split(",") if p.strip()]
            return [s]
        return []

    def gamma_get_market_by_slug(self, slug: str) -> dict | None:
        # Preferred documented endpoint: /markets/slug/{slug} :contentReference[oaicite:2]{index=2}
        slug_enc = urllib.parse.quote(slug, safe="")
        url = f"{GAMMA_HOST}/markets/slug/{slug_enc}"
        data = self._get_json(url)
        if isinstance(data, dict) and data.get("slug"):
            return data
        return None

    def resolve_slug_to_yes_no_token_ids(self, slug: str) -> tuple[str, str] | None:
        m = self.gamma_get_market_by_slug(slug)
        if not m:
            return None

        token_ids = self._parse_clob_token_ids(m.get("clobTokenIds"))
        if len(token_ids) < 2:
            return None

        # Convention is typically [YES, NO] for binary markets.
        return (token_ids[0], token_ids[1])
