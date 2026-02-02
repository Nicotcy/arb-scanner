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
    def __init__(self) -> None:
        self.client = KalshiPublicClient()

        # keep existing knobs if you already have them in env
        self.max_pages = int(os.getenv("KALSHI_PAGES", "3"))
        self.limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        # liquidity filters (if you had them already)
        self.min_liquidity = float(os.getenv("KALSHI_MIN_LIQ", "0"))
        self.require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") in {"1", "true", "yes", "on"}

        # blacklist behavior from your existing code
        self.blacklist_max_filtered_ratio = float(os.getenv("KALSHI_BLACKLIST_MAX_FILTERED_RATIO", "0.95"))

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        stats = KalshiStats()

        raw_markets = list(self.client.list_open_markets(max_pages=self.max_pages, limit_per_page=self.limit_per_page))
        stats.total = len(raw_markets) if raw_markets else 0

        # Your project had blacklist logic; keep it lightweight:
        # If blacklist filters almost everything, fall back to raw.
        filtered = self._apply_blacklist(raw_markets)
        if raw_markets:
            filtered_ratio = 1.0 - (len(filtered) / max(len(raw_markets), 1))
            if filtered_ratio > self.blacklist_max_filtered_ratio:
                print(
                    f"KalshiProvider: blacklist too aggressive (filtered={len(raw_markets)-len(filtered)} raw={len(raw_markets)}); using raw"
                )
                filtered = raw_markets

        for m in filtered:
            ticker = m.get("ticker")
            if not ticker:
                continue

            try:
                top = self.client.fetch_top_of_book(ticker)
            except Exception:
                stats.errors += 1
                continue

            # We cannot trust top-of-book yet (bid/ask unknown). Until fixed, treat as no prices.
            if top.yes_ask is None or top.no_ask is None:
                stats.noprices += 1
                continue

            # If later you fix bid/ask, this will start working again.
            yes_ask = top.yes_ask
            no_ask = top.no_ask
            yes_sz = float(top.yes_ask_qty or 0)
            no_sz = float(top.no_ask_qty or 0)

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

            # two-sided check (later will work when bids exist)
            if self.require_two_sided:
                if ob.best_yes_price is None or ob.best_no_price is None:
                    stats.one_sided += 1
                    continue

            stats.ok += 1
            stats.two_sided += 1
            yield MarketSnapshot(market=market, orderbook=ob)

        print(
            "KalshiProvider stats: "
            f"total={stats.total} ok={stats.ok} errors={stats.errors} "
            f"noprices={stats.noprices} liqskip={stats.liqskip} "
            f"one_sided={stats.one_sided} two_sided={stats.two_sided}"
        )

    def _apply_blacklist(self, markets: list[dict]) -> list[dict]:
        # Minimal placeholder: if you already have a richer blacklist, keep yours.
        # This keeps behavior stable.
        return markets

