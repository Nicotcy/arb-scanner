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
    """Lightweight client for Kalshi public endpoints (no auth)."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout_s: tuple[float, float] = (5.0, 10.0),
        page_limit: int = 50,
        sleep_s: float = 0.2,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.page_limit = page_limit
        self.sleep_s = sleep_s
        self.session = session or requests.Session()

    def list_open_markets(
        self, max_pages: int = 1, limit_per_page: int | None = None
    ) -> Iterable[dict[str, Any]]:
        """List open markets using small pagination."""

        if limit_per_page is None:
            limit_per_page = self.page_limit
        params: dict[str, Any] = {"status": "open", "limit": limit_per_page}
        pages = 0
        cursor: str | None = None

        while pages < max_pages:
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params=params)
            markets = payload.get("markets") or payload.get("results") or []
            for market in markets:
                yield market

            cursor = payload.get("next_cursor") or payload.get("cursor")
            pages += 1
            if not cursor:
                break
            time.sleep(self.sleep_s)

    def get_orderbook(self, ticker: str) -> dict[str, Any]:
        """Fetch raw orderbook for a market ticker."""

        return self._get(f"/markets/{ticker}/orderbook")

    def fetch_top_of_book(self, ticker: str) -> KalshiTopOfBook:
        """Return top-of-book prices/quantities for a market ticker."""

        payload = self.get_orderbook(ticker)
        if os.getenv("KALSHI_DEBUG_ORDERBOOK") == "1":
            print(f"orderbook debug ticker={ticker}")
            print(f"orderbook top-level keys={list(payload.keys())}")
            orderbook = payload.get("orderbook")
            if isinstance(orderbook, dict):
                print(f"orderbook keys={list(orderbook.keys())}")
            else:
                print("orderbook missing or not a dict")
            if isinstance(orderbook, dict):
                for side_key in ("yes", "no"):
                    side_value = orderbook.get(side_key)
                    if side_value is None:
                        print(
                            f"orderbook {side_key} missing, keys={list(orderbook.keys())}"
                        )
                        continue
                    if isinstance(side_value, dict):
                        print(
                            f"orderbook {side_key} keys={list(side_value.keys())}"
                        )
                        for nested_key, nested_value in side_value.items():
                            if isinstance(nested_value, dict):
                                print(
                                    f"orderbook {side_key}.{nested_key} keys="
                                    f"{list(nested_value.keys())}"
                                )
                            elif isinstance(nested_value, list):
                                print(
                                    f"orderbook {side_key}.{nested_key} list_len="
                                    f"{len(nested_value)}"
                                )
                    elif isinstance(side_value, list):
                        print(
                            f"orderbook {side_key} list_len={len(side_value)}"
                        )
                    else:
                        print(
                            f"orderbook {side_key} type={type(side_value).__name__}"
                        )
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
        response = self.session.get(url, params=params, timeout=self.timeout_s)
        response.raise_for_status()
        return response.json()


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
    if side is None:
        return None, None

    asks = None
    if isinstance(side, dict):
        asks = side.get("asks") or side.get("offers") or side.get("orders")
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


def normalize_kalshi_price(value: float | int | None) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 1.0:
        numeric = numeric / 100.0
    if numeric < 0.0:
        return 0.0
    if numeric > 1.0:
        return 1.0
    return numeric


def fetch_kalshi_top_of_book(ticker: str, client: KalshiPublicClient | None = None) -> KalshiTopOfBook:
    """Convenience helper to return a top-of-book snapshot."""

    active_client = client or KalshiPublicClient()
    return active_client.fetch_top_of_book(ticker)
