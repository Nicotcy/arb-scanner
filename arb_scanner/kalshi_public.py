"""Read-only Kalshi public market data client."""

from __future__ import annotations

from dataclasses import dataclass
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

    def list_open_markets(self, max_pages: int = 1) -> Iterable[dict[str, Any]]:
        """List open markets using small pagination."""

        params: dict[str, Any] = {"status": "open", "limit": self.page_limit}
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
        orderbook = payload.get("orderbook") or payload

        yes_bid, yes_qty = _extract_best_bid(orderbook.get("yes"))
        no_bid, no_qty = _extract_best_bid(orderbook.get("no"))

        yes_bid = _cents_to_dollars(yes_bid)
        no_bid = _cents_to_dollars(no_bid)

        yes_ask = None if no_bid is None else 1.0 - no_bid
        no_ask = None if yes_bid is None else 1.0 - yes_bid

        return KalshiTopOfBook(
            ticker=ticker,
            yes_bid=yes_bid,
            yes_ask=yes_ask,
            no_bid=no_bid,
            no_ask=no_ask,
            yes_bid_qty=yes_qty,
            no_bid_qty=no_qty,
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


def fetch_kalshi_top_of_book(ticker: str, client: KalshiPublicClient | None = None) -> KalshiTopOfBook:
    """Convenience helper to return a top-of-book snapshot."""

    active_client = client or KalshiPublicClient()
    return active_client.fetch_top_of_book(ticker)
