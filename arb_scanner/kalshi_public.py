"""Read-only Kalshi public market data client.

IMPORTANT:
The public /trade-api/v2/markets/{ticker}/orderbook endpoint we can access returns
a single list per outcome (yes/no). It does NOT separate bids vs asks.

Therefore, we cannot safely infer a tradeable top-of-book (bid/ask) from it.
Until a proper endpoint exists (or we validate the semantics), we return None
for bid/ask to avoid fake edges.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any

import requests


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class KalshiTopOfBook:
    ticker: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_bid_qty: float | None
    no_bid_qty: float | None
    yes_ask_qty: float | None
    no_ask_qty: float | None


class KalshiPublicClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("KALSHI_BASE_URL", BASE_URL)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": os.getenv(
                    "KALSHI_UA",
                    "arb-scanner/0.1 (+https://example.local; read-only)",
                )
            }
        )
        self.timeout = float(os.getenv("KALSHI_TIMEOUT", "15"))

    def list_open_markets(self, max_pages: int = 3, limit_per_page: int = 200):
        cursor = None
        pages = 0

        while pages < max_pages:
            params: dict[str, Any] = {"status": "open", "limit": limit_per_page}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params=params)
            markets = payload.get("markets") or []
            for m in markets:
                yield m
            cursor = payload.get("cursor")
            pages += 1
            if not cursor:
                break

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}/orderbook")

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}")

    def probe_endpoints(self, ticker: str) -> list[dict[str, Any]]:
        candidates = [
            f"/markets/{ticker}/orderbook",
            f"/markets/{ticker}/orderbook?depth=1",
            f"/markets/{ticker}/orderbook?depth=5",
            f"/markets/{ticker}",
            f"/markets/{ticker}/prices",
            f"/markets/{ticker}/orderbook_summary",
            f"/markets/{ticker}/orderbook-top",
            f"/markets/{ticker}/book",
        ]

        out: list[dict[str, Any]] = []
        for path in candidates:
            try:
                payload = self._get(path, params=None, raw_path=True)
                out.append(_summarize_payload(path, payload))
            except Exception as e:
                out.append({"path": path, "ok": False, "error": str(e)})
        return out

    def fetch_top_of_book(self, ticker: str) -> KalshiTopOfBook:
        """
        Conservative behavior:
        returns None for bids/asks until we can reliably infer tradeable bid/ask.
        """
        return KalshiTopOfBook(
            ticker=ticker,
            yes_bid=None,
            yes_ask=None,
            no_bid=None,
            no_ask=None,
            yes_bid_qty=None,
            no_bid_qty=None,
            yes_ask_qty=None,
            no_ask_qty=None,
        )

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        raw_path: bool = False,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}" if raw_path else f"{self.base_url}{path}"

        for attempt in range(5):
            try:
                resp = self.session.get(url, params=params if not raw_path else None, timeout=self.timeout)
                if resp.status_code == 429:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException:
                if attempt == 4:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError("unreachable")


def _summarize_payload(path: str, payload: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {"path": path, "ok": True, "type": type(payload).__name__}

    if isinstance(payload, dict):
        keys = list(payload.keys())
        summary["keys"] = keys[:30]
        ob = payload.get("orderbook") if "orderbook" in payload else None
        if isinstance(ob, dict):
            summary["orderbook_keys"] = list(ob.keys())[:30]
            for side in ("yes", "no"):
                v = ob.get(side)
                summary[f"orderbook_{side}_type"] = type(v).__name__
                if isinstance(v, dict):
                    summary[f"{side}_keys"] = list(v.keys())[:30]
                elif isinstance(v, list):
                    summary[f"{side}_len"] = len(v)
                    summary[f"{side}_head"] = v[:3]
        return summary

    if isinstance(payload, list):
        summary["len"] = len(payload)
        summary["head"] = payload[:3]
        return summary

    return summary
