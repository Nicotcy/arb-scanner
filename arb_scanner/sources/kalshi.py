"""Kalshi market data provider (read-only via public API)."""

from __future__ import annotations

import os
from collections.abc import Iterable

from arb_scanner.kalshi_public import KalshiPublicClient
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


class KalshiProvider(MarketDataProvider):
    """MarketDataProvider implementation for Kalshi (public read-only API)."""

    def __init__(self) -> None:
        self.client = KalshiPublicClient()

    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        # Configuración
        max_pages = int(os.getenv("KALSHI_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))
        require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") == "1"
        min_liq = float(os.getenv("KALSHI_MIN_LIQ", "1"))
        max_tickers = int(os.getenv("KALSHI_MAX_TICKERS", "300"))

        # 1) Listado de mercados
        markets_raw = list(
            self.client.list_open_markets(
                max_pages=max_pages,
                limit_per_page=limit_per_page,
            )
        )

        # 2) Blacklist básica (MVEs gigantes)
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
        blacklist_substrings = ("MULTIGAMEEXTENDED",)

        markets_filtered = [
            m
            for m in markets_raw
            if not any((m.get("ticker") or "").startswith(p) for p in blacklist_prefixes)
            and not any(s in (m.get("ticker") or "") for s in blacklist_substrings)
        ]

        min_after_blacklist = int(os.getenv("KALSHI_MIN_AFTER_BLACKLIST", "50"))
        if len(markets_filtered) < min_after_blacklist:
            print(
                f"KalshiProvider: blacklist too aggressive "
                f"(filtered={len(markets_filtered)} raw={len(markets_raw)}); using raw"
            )
            markets = markets_raw
        else:
            markets = markets_filtered

        # 3) Expandir MVEs a legs tradeables
        tickers_to_fetch: list[str] = []
        seen: set[str] = set()

        for market in markets:
            t = market.get("ticker")
            if not t:
                continue

            legs = market.get("mve_selected_legs") or []
            if legs:
                for leg in legs:
                    lt = leg.get("market_ticker")
                    if lt and lt not in seen:
                        tickers_to_fetch.append(lt)
                        seen.add(lt)
            else:
                if t not in seen:
                    tickers_to_fetch.append(t)
                    seen.add(t)

        # 4) Contadores (IMPORTANTE: estaban rotos antes)
        total = 0
        ok = 0
        fetch_errors = 0
        noprices = 0
        liqskip = 0
        one_sided = 0
        two_sided = 0

        # 5) Fetch top-of-book real
        for ticker in tickers_to_fetch:
            if total >= max_tickers:
                break
            total += 1

            try:
                top = self.client.fetch_top_of_book(ticker)
            except Exception:
                fetch_errors += 1
                continue

            has_yes = top.yes_ask is not None
            has_no = top.no_ask is not None

            if not has_yes and not has_no:
                noprices += 1
                continue

            if require_two_sided and not (has_yes and has_no):
                one_sided += 1
                continue

            yes_size = float(top.yes_ask_qty or 0)
            no_size = float(top.no_ask_qty or 0)

            if has_yes and has_no and min(yes_size, no_size) < min_liq:
                liqskip += 1
                continue

            if has_yes and has_no:
                two_sided += 1
            else:
                one_sided += 1

            snapshot = MarketSnapshot(
                market=Market(
                    venue=self.name(),
                    market_id=ticker,
                    question=ticker,
                    outcomes=("Yes", "No"),
                ),
                orderbook=OrderBookTop(
                    best_yes_price=top.yes_ask,
                    best_yes_size=yes_size,
                    best_no_price=top.no_ask,
                    best_no_size=no_size,
                ),
            )

            ok += 1
            yield snapshot

        # 6) Stats finales
        print(
            "KalshiProvider stats: "
            f"total={total} ok={ok} errors={fetch_errors} "
            f"noprices={noprices} liqskip={liqskip} "
            f"one_sided={one_sided} two_sided={two_sided}"
        )
