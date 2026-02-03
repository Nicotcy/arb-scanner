"""Read-only Kalshi public market data client.

Kalshi public orderbook returns ONLY bids (not asks) for YES and NO.
Asks can be derived via complementarity in binary markets:

- YES ask at price A is equivalent to a NO bid at (100 - A)
  => YES_ASK = 100 - NO_BID
- NO ask at price B is equivalent to a YES bid at (100 - B)
  => NO_ASK  = 100 - YES_BID

We compute top-of-book bid/ask from returned bids.

IMPORTANT (2026 reality check):
- /markets?status=open often includes many multivariate (MVE / combo) tickers (e.g., KXMVE...).
  Those are NOT standard binary YES/NO markets with the normal orderbook shape.
- For a practical scanner, enumerating from /events with nested markets is more reliable:
  GET /events?status=open&with_nested_markets=true
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Any, Iterable, Tuple

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
    """Minimal read-only client with *fast failure* on network issues.

    Design choice:
      - Let the outer daemon loop handle exponential backoff.
      - Keep client-side retries small and focused (429 / occasional 5xx), so we don't "pause silently"
        for 60-120 seconds when Wi-Fi/DNS breaks.

    Tuning via env:
      - KALSHI_CONNECT_TIMEOUT (default 3.0)
      - KALSHI_READ_TIMEOUT    (default 12.0)
      - KALSHI_HTTP_ATTEMPTS   (default 2)  # total attempts for 429/5xx
      - KALSHI_HTTP_DEBUG      (default 0)  # 1 to print per-attempt debug
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("KALSHI_BASE_URL", BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": os.getenv(
                    "KALSHI_UA",
                    "arb-scanner/0.1 (+https://example.local; read-only)",
                )
            }
        )

        # Use separate connect/read timeouts (tuple) so DNS/Wi-Fi failures surface quickly.
        self.connect_timeout = float(os.getenv("KALSHI_CONNECT_TIMEOUT", "3"))
        self.read_timeout = float(os.getenv("KALSHI_READ_TIMEOUT", "12"))
        self.timeout: Tuple[float, float] = (self.connect_timeout, self.read_timeout)

        # Small retry budget; outer daemon handles backoff.
        self.http_attempts = int(os.getenv("KALSHI_HTTP_ATTEMPTS", "2"))
        self.debug = os.getenv("KALSHI_HTTP_DEBUG", "0") == "1"

        # How to enumerate "open" tradeable markets:
        # - "events" is recommended (filters out lots of MVE junk for scanner purposes)
        # - "markets" is legacy (can be MVE-heavy)
        self.market_list_source = os.getenv("KALSHI_MARKET_LIST_SOURCE", "events").strip().lower()

    def list_open_markets(self, max_pages: int = 3, limit_per_page: int = 200) -> Iterable[dict[str, Any]]:
        """Yields market objects (dicts) likely to be binary tradeable markets."""
        if self.market_list_source == "markets":
            yield from self._list_open_markets_from_markets(max_pages=max_pages, limit_per_page=limit_per_page)
            return
        yield from self._list_open_markets_from_events(max_pages=max_pages, limit_per_page=limit_per_page)

    def _list_open_markets_from_markets(self, max_pages: int = 3, limit_per_page: int = 200):
        cursor = None
        pages = 0

        while pages < max_pages:
            params: dict[str, Any] = {"status": "open", "limit": limit_per_page}
            if cursor:
                params["cursor"] = cursor
            payload = self._get("/markets", params=params)

            markets = payload.get("markets") or []
            for m in markets:
                ticker = (m.get("ticker") or "").strip()
                if not ticker:
                    continue
                if ticker.upper().startswith("KXMVE"):
                    continue
                yield m

            cursor = payload.get("cursor")
            pages += 1
            if not cursor:
                break

    def _list_open_markets_from_events(self, max_pages: int = 3, limit_per_page: int = 200):
        cursor = None
        pages = 0

        while pages < max_pages:
            params: dict[str, Any] = {
                "status": "open",
                "limit": limit_per_page,
                "with_nested_markets": "true",
            }
            if cursor:
                params["cursor"] = cursor

            payload = self._get("/events", params=params)

            events = payload.get("events") or []
            for ev in events:
                markets = ev.get("markets") or []
                if not isinstance(markets, list):
                    continue

                for m in markets:
                    if not isinstance(m, dict):
                        continue
                    ticker = (m.get("ticker") or "").strip()
                    if not ticker:
                        continue
                    if ticker.upper().startswith("KXMVE"):
                        continue
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
        payload = self.get_orderbook(ticker, depth=1)
        ob = payload.get("orderbook") if isinstance(payload, dict) else None
        if not isinstance(ob, dict):
            return KalshiTopOfBook(ticker, None, None, None, None, None, None, None, None)

        yes_list = ob.get("yes")
        no_list = ob.get("no")

        yes_bid_cents, yes_bid_qty = _best_bid_from_levels(yes_list)
        no_bid_cents, no_bid_qty = _best_bid_from_levels(no_list)

        yes_bid = _cents_to_dollars(yes_bid_cents)
        no_bid = _cents_to_dollars(no_bid_cents)

        yes_ask_cents = (100 - no_bid_cents) if no_bid_cents is not None else None
        no_ask_cents = (100 - yes_bid_cents) if yes_bid_cents is not None else None

        yes_ask = _cents_to_dollars(yes_ask_cents)
        no_ask = _cents_to_dollars(no_ask_cents)

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
        # raw_path exists mainly because some call-sites include querystring already.
        url = f"{self.base_url}{path}" if raw_path else f"{self.base_url}{path}"

        attempts = max(1, int(self.http_attempts))
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                if self.debug:
                    print(f"[kalshi_http] GET {path} attempt={attempt+1}/{attempts}")
                resp = self.session.get(url, params=params if not raw_path else None, timeout=self.timeout)

                # Small, focused retry handling.
                if resp.status_code == 429:
                    sleep_s = 0.6 * (attempt + 1)
                    if self.debug:
                        print(f"[kalshi_http] 429 rate limit; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue

                if 500 <= resp.status_code < 600 and attempt < attempts - 1:
                    sleep_s = 0.4 * (attempt + 1)
                    if self.debug:
                        print(f"[kalshi_http] {resp.status_code} server error; sleeping {sleep_s:.1f}s")
                    time.sleep(sleep_s)
                    continue

                resp.raise_for_status()
                return resp.json()

            except requests.RequestException as e:
                last_exc = e
                if attempt >= attempts - 1:
                    raise
                sleep_s = 0.25 * (attempt + 1)
                if self.debug:
                    print(f"[kalshi_http] exception={type(e).__name__}; sleeping {sleep_s:.2f}s")
                time.sleep(sleep_s)

        raise RuntimeError(f"Kalshi GET failed after {attempts} attempts: {last_exc}")


def _best_bid_from_levels(levels: Any) -> tuple[int | None, float | None]:
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
