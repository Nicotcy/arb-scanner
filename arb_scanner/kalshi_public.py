"""Read-only Kalshi public market data client."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Iterable

import requests


BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


@dataclass(frozen=True)
class KalshiTopOfBook:
    ticker: str
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_bid_qty: int | None
    no_bid_qty: int | None
    yes_ask_qty: int | None
    no_ask_qty: int | None


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

    def list_open_markets(
        self, max_pages: int = 3, limit_per_page: int = 200
    ) -> Iterable[dict[str, Any]]:
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

    def fetch_top_of_book(self, ticker: str) -> KalshiTopOfBook:
        payload = self.get_orderbook(ticker)

        if os.getenv("KALSHI_DEBUG_ORDERBOOK") == "1":
            print(f"orderbook debug ticker={ticker}")
            print(f"orderbook top-level keys={list(payload.keys())}")
            orderbook = payload.get("orderbook")
            if isinstance(orderbook, dict):
                print(f"orderbook keys={list(orderbook.keys())}")

        orderbook = payload.get("orderbook") or payload

        yes_bid, yes_bid_qty = _extract_best_bid(orderbook.get("yes"))
        no_bid, no_bid_qty = _extract_best_bid(orderbook.get("no"))
        yes_ask, yes_ask_qty = _extract_best_ask(orderbook.get("yes"))
        no_ask, no_ask_qty = _extract_best_ask(orderbook.get("no"))

        yes_bid = _cents_to_dollars(yes_bid)
        no_bid = _cents_to_dollars(no_bid)
        yes_ask = _cents_to_dollars(yes_ask)
        no_ask = _cents_to_dollars(no_ask)

        return KalshiTopOfBook(
            ticker=ticker,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            yes_bid_qty=yes_bid_qty,
            no_bid_qty=no_bid_qty,
            yes_ask_qty=yes_ask_qty,
            no_ask_qty=no_ask_qty,
        )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        for attempt in range(5):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
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


def _extract_best_bid(side: Any) -> tuple[int | None, int | None]:
    if side is None:
        return None, None

    bids = None
    if isinstance(side, dict):
        bids = side.get("bids") or side.get("orders")
    else:
        bids = side

    if not bids:
        return None, None

    best_price: int | None = None
    best_qty: int | None = None

    for bid in bids:
        price = None
        qty = None
        if isinstance(bid, dict):
            price = bid.get("price") or bid.get("p")
            qty = bid.get("quantity") or bid.get("size") or bid.get("qty")
        elif isinstance(bid, (list, tuple)) and len(bid) >= 2:
            price, qty = bid[0], bid[1]

        price = _coerce_int(price)
        qty = _coerce_int(qty)

        if price is None:
            continue
        if best_price is None or price > best_price:
            best_price = price
            best_qty = qty

    return best_price, best_qty


def _extract_best_ask(side: Any) -> tuple[int | None, int | None]:
    """
    IMPORTANT: For asks, we do NOT fall back to "orders".
    In some Kalshi payloads, "orders" may represent bids or mixed orders,
    which creates fake 1-cent asks everywhere.
    """
    if side is None:
        return None, None

    asks = None
    if isinstance(side, dict):
        asks = side.get("asks") or side.get("offers")
    else:
        asks = side

    if not asks:
        return None, None

    best_price: int | None = None
    best_qty: int | None = None

    for ask in asks:
        price = None
        qty = None
        if isinstance(ask, dict):
            price = ask.get("price") or ask.get("p")
            qty = ask.get("quantity") or ask.get("size") or ask.get("qty")
        elif isinstance(ask, (list, tuple)) and len(ask) >= 2:
            price, qty = ask[0], ask[1]

        price = _coerce_int(price)
        qty = _coerce_int(qty)

        if price is None:
            continue
        if best_price is None or price < best_price:
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


def _cents_to_dollars(value: int | None) -> float | None:
    if value is None:
        return None
    return value / 100
