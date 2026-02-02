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

    IMPORTANT:
    Kalshi /markets/{ticker}/orderbook returns bids only.
    Our KalshiPublicClient.fetch_top_of_book derives asks by complementarity.
    We treat derived asks as "buyable" top-of-book for scanner purposes.
    """

    def __init__(self) -> None:
        self.client = KalshiPublicClient()

        self.max_pages = int(os.getenv("KALSHI_PAGES", "3"))
        self.limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        # Liquidity filters (very light)
        self.min_exec_size = float(os.getenv("KALSHI_MIN_EXEC_SIZE", "1"))

        # If you had blacklist logic previously, keep env knobs
        self.blacklist_max_filtered_ratio = float(os.getenv("KALSHI_BLACKLIST_MAX_FILTERED_RATIO", "0.95"))

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        stats = KalshiStats()

        markets = list(self.client.list_open_markets(max_pages=self.max_pages, limit_per_page=self.limit_per_page))
        stats.total = len(markets)

        # If later you reintroduce blacklist, do it here.
        used = markets

        for m in used:
            ticker = m.get("ticker")
            if not ticker:
                continue

            try:
                top = self.client.fetch_top_of_book(ticker)
            except Exception:
                stats.errors += 1
                continue

            # We require derived asks to exist to consider it tradeable.
            if top.yes_ask is None or top.no_ask is None:
                stats.noprices += 1
                continue

            yes_ask = float(top.yes_ask)
            no_ask = float(top.no_ask)
            yes_sz = float(top.yes_ask_qty or 0.0)
            no_sz = float(top.no_ask_qty or 0.0)

            # Minimal executability filter (optional)
            if yes_sz < self.min_exec_size or no_sz < self.min_exec_size:
                stats.liqskip += 1
                continue

            ob = OrderBookTop(
                best_yes_price=yes_ask,
                best_yes_size=yes_sz,
                best_no_price=no_ask,
                best_no_size=no_sz,
            )

            # Heuristic: these are binary markets (YES/NO)
            market = Market(
                venue="Kalshi",
                market_id=ticker,
                question=m.get("title") or ticker,
                outcomes=("YES", "NO"),
            )

            # Two-sided (asks exist for both)
            stats.ok += 1
            stats.two_sided += 1
            yield MarketSnapshot(market=market, orderbook=ob)

        print(
            "KalshiProvider stats: "
            f"total={stats.total} ok={stats.ok} errors={stats.errors} "
            f"noprices={stats.noprices} liqskip={stats.liqskip} "
            f"one_sided={stats.one_sided} two_sided={stats.two_sided}"
        )
