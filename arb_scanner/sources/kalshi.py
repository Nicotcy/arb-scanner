from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from arb_scanner.kalshi_public import KalshiPublicClient
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop


@dataclass
class KalshiStats:
    total: int = 0
    ok: int = 0
    errors: int = 0
    noprices: int = 0
    liqskip: int = 0
    one_sided: int = 0
    two_sided: int = 0


class KalshiProvider:
    """
    Read-only provider using Kalshi public trade-api.

    Kalshi orderbook returns bids-only per outcome; asks are derived in KalshiPublicClient.fetch_top_of_book().
    We treat derived asks as buyable top-of-book for scanner purposes.
    """

    def __init__(self) -> None:
        self.client = KalshiPublicClient()

        self.max_pages = int(os.getenv("KALSHI_PAGES", "3"))
        self.limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        # Minimal executability filter (can be overridden)
        self.min_exec_size = float(os.getenv("KALSHI_MIN_EXEC_SIZE", "1.0"))

        # Tiny debug to explain why we get noprices=all
        self.debug = os.getenv("KALSHI_PROVIDER_DEBUG", "0") in {"1", "true", "yes", "on"}
        self.debug_limit = int(os.getenv("KALSHI_PROVIDER_DEBUG_LIMIT", "3"))

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        stats = KalshiStats()

        markets = list(self.client.list_open_markets(max_pages=self.max_pages, limit_per_page=self.limit_per_page))
        stats.total = len(markets)

        dbg_printed = 0

        for m in markets:
            ticker = m.get("ticker")
            if not ticker:
                continue

            try:
                top = self.client.fetch_top_of_book(ticker)
            except Exception as e:
                stats.errors += 1
                if self.debug and dbg_printed < self.debug_limit:
                    print(f"[KALSHI_PROVIDER_DEBUG] ERROR ticker={ticker} err={e}")
                    dbg_printed += 1
                continue

            if self.debug and dbg_printed < self.debug_limit:
                print(
                    "[KALSHI_PROVIDER_DEBUG] "
                    f"ticker={ticker} yes_bid={top.yes_bid} yes_ask={top.yes_ask} "
                    f"no_bid={top.no_bid} no_ask={top.no_ask} "
                    f"yes_ask_qty={top.yes_ask_qty} no_ask_qty={top.no_ask_qty}"
                )
                dbg_printed += 1

            # Require derived asks to exist
            if top.yes_ask is None or top.no_ask is None:
                stats.noprices += 1
                continue

            yes_ask = float(top.yes_ask)
            no_ask = float(top.no_ask)
            yes_sz = float(top.yes_ask_qty or 0.0)
            no_sz = float(top.no_ask_qty or 0.0)

            if yes_sz < self.min_exec_size or no_sz < self.min_exec_size:
                stats.liqskip += 1
                continue

            ob = OrderBookTop(
                best_yes_price=yes_ask,
                best_yes_size=yes_sz,
                best_no_price=no_ask,
                best_no_size=no_sz,
            )

            market = Market(
                venue="Kalshi",
                market_id=ticker,
                question=m.get("title") or ticker,
                outcomes=("YES", "NO"),
            )

            stats.ok += 1
            stats.two_sided += 1
            yield MarketSnapshot(market=market, orderbook=ob)

        print(
            "KalshiProvider stats: "
            f"total={stats.total} ok={stats.ok} errors={stats.errors} "
            f"noprices={stats.noprices} liqskip={stats.liqskip} "
            f"one_sided={stats.one_sided} two_sided={stats.two_sided}"
        )
