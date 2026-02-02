"""Read-only Kalshi public market data client.

Kalshi public orderbook returns ONLY bids (not asks) for YES and NO.
Asks can be derived via complementarity in binary markets:

- YES ask at price A is equivalent to a NO bid at (100 - A)
  => YES_ASK = 100 - NO_BID
- NO ask at price B is equivalent to a YES bid at (100 - B)
  => NO_ASK  = 100 - YES_BID

Docs:
- Get Market Orderbook: orderbook shows active bid orders only.
- Orderbook responses: explains why only bids are returned.

We therefore compute top-of-book bid/ask from returned bids.
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

    def get_orderbook(self, ticker: str, depth: int | None = None) -> dict[str, Any]:
        path = f"/markets/{ticker}/orderbook"
        if depth is not None:
            path = f"{path}?depth={int(depth)}"
            return self._get(path, params=None, raw_path=True)
        return self._get(path, params=None, raw_path=True)

    def get_market(self, ticker: str) -> dict[str, Any]:
        return self._get(f"/markets/{ticker}", params=None, raw_path=True)

    def probe_endpoints(self, ticker: str) -> list[dict[str, Any]]:
        candidates = [
            f"/markets/{ticker}/orderbook",
            f"/markets/{ticker}/orderbook?depth=1",
            f"/markets/{ticker}/orderbook?depth=5",
            f"/markets/{ticker}",
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
        Returns top-of-book bid/ask in DOLLARS (0.00-1.00) plus quantities.

        Uses depth=1 to minimize payload:
        - best YES bid is payload['orderbook']['yes'][0][0] (in cents)
        - best NO  bid is payload['orderbook']['no'][0][0] (in cents)

        Derived asks:
        - yes_ask_cents = 100 - no_bid_cents
        - no_ask_cents  = 100 - yes_bid_cents

        Quantities:
        - yes_ask_qty corresponds to size at NO bid level used for derivation
        - no_ask_qty  corresponds to size at YES bid level used for derivation
        """
        payload = self.get_orderbook(ticker, depth=1)
        ob = payload.get("orderbook") if isinstance(payload, dict) else None
        if not isinstance(ob, dict):
            return KalshiTopOfBook(ticker, None, None, None, None, None, None, None, None)

        yes_list = ob.get("yes")
        no_list = ob.get("no")

        yes_bid_cents, yes_bid_qty = _best_bid_from_levels(yes_list)
        no_bid_cents, no_bid_qty = _best_bid_from_levels(no_list)

        # Convert bids to dollars
        yes_bid = _cents_to_dollars(yes_bid_cents)
        no_bid = _cents_to_dollars(no_bid_cents)

        # Derive asks (still in cents)
        yes_ask_cents = (100 - no_bid_cents) if no_bid_cents is not None else None
        no_ask_cents = (100 - yes_bid_cents) if yes_bid_cents is not None else None

        yes_ask = _cents_to_dollars(yes_ask_cents)
        no_ask = _cents_to_dollars(no_ask_cents)

        # Derived ask sizes come from the complementary bid sizes
        yes_ask_qty = float(no_bid_qty) if no_bid_qty is not None else None
        no_ask_qty = float(yes_bid_qty) if yes_bid_qty is not None else None

        return KalshiTopOfBook(
            ticker=ticker,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            yes_bid_qty=float(yes_bid_qty) if yes_bid_qty is not None else None,
            no_bid_qty=float(no_bid_qty) if no_bid_qty is not None else None,
            yes_ask_qty=yes_ask_qty,
            no_ask_qty=no_ask_qty,
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


def _best_bid_from_levels(levels: Any) -> tuple[int | None, float | None]:
    """
    levels is typically a list like [[price_cents, qty], ...]
    With depth=1 it should be exactly one element: top bid.
    We still handle general cases.
    """
    if not isinstance(levels, list) or not levels:
        return None, None

    best_price: int | None = None
    best_qty: float | None = None

    for lvl in levels:
        if not isinstance(lvl, (list, tuple)) or len(lvl) < 2:
            continue
        price = _coerce_int(lvl[0])
        qty = _coerce_float(lvl[1])
        if price is None:
            continue
        if best_price is None or price > best_price:
            best_price = price
            best_qty = qty

    return best_price, best_qty


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cents_to_dollars(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 100.0


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
                if isinstance(v, list):
                    summary[f"{side}_len"] = len(v)
                    summary[f"{side}_head"] = v[:3]
        return summary

    if isinstance(payload, list):
        summary["len"] = len(payload)
        summary["head"] = payload[:3]
        return summary

    return summary

