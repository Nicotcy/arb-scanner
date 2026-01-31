from __future__ import annotations

import os
from typing import Iterable, Any

from arb_scanner.kalshi_public import KalshiPublicClient
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop


class KalshiProvider:
    """
    Read-only Kalshi snapshot provider.

    Usamos el payload de list_open_markets (yes_ask/no_ask + qty). Es lo más
    estable para un scanner read-only sin depender del endpoint de orderbook.
    """

    def __init__(self) -> None:
        self.client = KalshiPublicClient()

    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        max_pages = int(os.getenv("KALSHI_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        markets = list(
            self.client.list_open_markets(
                max_pages=max_pages,
                limit_per_page=limit_per_page,
            )
        )
        markets_raw = markets

        # Intento de filtrar MVEs umbrella (no tradeables directamente)
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
        blacklist_substrings = ("MULTIGAMEEXTENDED",)

        markets_filtered = [
            m
            for m in markets
            if not any((m.get("ticker") or "").startswith(p) for p in blacklist_prefixes)
            and not any(s in (m.get("ticker") or "") for s in blacklist_substrings)
        ]

        min_after_blacklist = int(os.getenv("KALSHI_MIN_AFTER_BLACKLIST", "50"))
        if len(markets_filtered) < min_after_blacklist:
            print(
                "KalshiProvider: blacklist too aggressive "
                f"(filtered={len(markets_filtered)} raw={len(markets_raw)}); using raw"
            )
            markets = markets_raw
        else:
            markets = markets_filtered

        # Mantener mercados activos si hay suficientes
        min_active = int(os.getenv("KALSHI_MIN_ACTIVE", "50"))
        max_tickers = int(os.getenv("KALSHI_MAX_TICKERS", "300"))

        for key in ("volume_24h", "volume", "open_interest"):
            active_markets = [m for m in markets if (m.get(key) or 0) > 0]
            if len(active_markets) >= min_active:
                markets = sorted(active_markets, key=lambda m: m.get(key) or 0, reverse=True)
                break

        # Lookup por ticker usando RAW (para que existan los legs)
        by_ticker: dict[str, dict[str, Any]] = {}
        for m in markets_raw:
            t = m.get("ticker")
            if t:
                by_ticker[t] = m

        # Construir lista de tickers tradeables (expandiendo MVEs a legs)
        tickers_to_fetch: list[str] = []
        seen: set[str] = set()

        for m in markets:
            ticker = m.get("ticker")
            if not ticker:
                continue

            if ticker.startswith("KXMVE") or "MULTIGAMEEXTENDED" in ticker:
                legs = m.get("mve_selected_legs") or []
                for leg in legs:
                    leg_ticker = leg.get("market_ticker")
                    if not leg_ticker or leg_ticker in seen:
                        continue
                    tickers_to_fetch.append(leg_ticker)
                    seen.add(leg_ticker)
                continue

            if ticker not in seen:
                tickers_to_fetch.append(ticker)
                seen.add(ticker)

        require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") == "1"
       

        min_liq = float(os.getenv("KALSHI_MIN_LIQ", "1"))

        total = 0
        ok = 0
        skipped_missing = 0
        skipped_no_price = 0
        skipped_liq = 0
        one_sided = 0
        two_sided = 0

        for ticker in tickers_to_fetch:
            if total >= max_tickers:
                break
            total += 1

            m = by_ticker.get(ticker)
            if not m:
                skipped_missing += 1
                continue

            yes_ask = m.get("yes_ask")
            no_ask = m.get("no_ask")

            if yes_ask is None or no_ask is None:
                skipped_no_price += 1
                continue

            yes_price = float(yes_ask) / 100.0
            no_price = float(no_ask) / 100.0

            yes_size = float(m.get("yes_ask_qty") or 0)
            no_size = float(m.get("no_ask_qty") or 0)

            has_yes = yes_ask is not None
            has_no = no_ask is not None

            if require_two_sided and not (has_yes and has_no):
                continue

            if has_yes and has_no and min(yes_size, no_size) < min_liq:
                skipped_liq += 1
                continue

            ok += 1
            if has_yes and has_no:
                two_sided += 1
            else:
                one_sided += 1

            yield MarketSnapshot(
                market=Market(
                    venue=self.name(),
                    market_id=ticker,
                    question=m.get("title") or ticker,
                    outcomes=("Yes", "No"),
                ),
                orderbook=OrderBookTop(
                    best_yes_price=yes_price,
                    best_yes_size=yes_size,
                    best_no_price=no_price,
                    best_no_size=no_size,
                ),
            )

        print(
            "KalshiProvider stats: "
            f"total={total} ok={ok} "
            f"missing={skipped_missing} noprices={skipped_no_price} liqskip={skipped_liq} "
            f"one_sided={one_sided} two_sided={two_sided}"
        )
