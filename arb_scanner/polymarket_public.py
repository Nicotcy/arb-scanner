from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

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
    """Read-only client for Gamma + CLOB, tuned for daemon use.

    Env tuning:
      - POLY_TIMEOUT_S      (default 12)
      - POLY_HTTP_ATTEMPTS  (default 2)
      - POLY_HTTP_DEBUG     (default 0)
      - POLYMARKET_INSECURE_SSL=1 (not recommended, but exists)
    """

    def __init__(self) -> None:
        self.timeout_s = float(os.getenv("POLY_TIMEOUT_S", "12"))
        self.http_attempts = int(os.getenv("POLY_HTTP_ATTEMPTS", "2"))
        self.debug = os.getenv("POLY_HTTP_DEBUG", "0") == "1"

    def _ssl_context(self) -> ssl.SSLContext:
        if os.getenv("POLYMARKET_INSECURE_SSL", "0") == "1":
            return ssl._create_unverified_context()

        try:
            import certifi  # type: ignore

            return ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return ssl.create_default_context()

    def _default_headers(self) -> dict[str, str]:
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
        ctx = self._ssl_context()
        headers = self._default_headers()
        attempts = max(1, int(self.http_attempts))

        last_err: Exception | None = None

        for attempt in range(attempts):
            try:
                if self.debug:
                    print(f"[poly_http] GET {url} attempt={attempt+1}/{attempts}")

                req = urllib.request.Request(url, method="GET", headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout_s, context=ctx) as resp:
                    status = getattr(resp, "status", 200)
                    body = resp.read().decode("utf-8")

                if status == 429:
                    sleep_s = 0.6 * (attempt + 1)
                    if self.debug:
                        print(f"[poly_http] 429 rate limit; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue

                if 500 <= int(status) < 600 and attempt < attempts - 1:
                    sleep_s = 0.4 * (attempt + 1)
                    if self.debug:
                        print(f"[poly_http] {status} server error; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue

                return json.loads(body)

            except HTTPError as e:
                last_err = e
                code = getattr(e, "code", None)
                if code == 429 and attempt < attempts - 1:
                    sleep_s = 0.6 * (attempt + 1)
                    if self.debug:
                        print(f"[poly_http] 429 HTTPError; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue
                if code is not None and 500 <= int(code) < 600 and attempt < attempts - 1:
                    sleep_s = 0.4 * (attempt + 1)
                    if self.debug:
                        print(f"[poly_http] {code} HTTPError; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue
                raise

            except URLError:
                # DNS / connection failures -> fail fast.
                raise

            except Exception as e:
                last_err = e
                if attempt >= attempts - 1:
                    raise
                sleep_s = 0.25 * (attempt + 1)
                if self.debug:
                    print(f"[poly_http] exception={type(e).__name__}; sleeping {sleep_s:.2f}s")
                time.sleep(sleep_s)

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

        return (token_ids[0], token_ids[1])
