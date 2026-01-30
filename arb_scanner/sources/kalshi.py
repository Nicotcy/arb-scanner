from __future__ import annotations

import os
from collections.abc import Iterable
from typing import Any

from arb_scanner.kalshi_public import KalshiPublicClient
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider


def _is_mve_ticker(ticker: str) -> bool:
    # "MVE" wrappers (no son lo que quieres pricear/ejecutar)
    return ticker.startswith("KXMVE") or ("MULTIGAMEEXTENDED" in ticker)


class KalshiProvider(MarketDataProvider):
    def __init__(self) -> None:
        self.client = KalshiPublicClient()

    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        """
        Fetch snapshots from Kalshi (read-only):
        - Lista markets open
        - Filtra ruido (opcional)
        - IMPORTANTE: si el market es MVE, expandimos sus legs (mve_selected_legs)
        - Pide top-of-book por ticker tradeable (legs)
        """

        client = self.client

        max_pages = int(os.getenv("KALSHI_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        markets_raw = list(
            client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page)
        )

        # Blacklist suave (para evitar basura concreta si te inunda)
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
        blacklist_substrings = ("MULTIGAMEEXTENDED",)

        markets_filtered = [
            market
            for market in markets_raw
            if not any(
                (market.get("ticker") or "").startswith(prefix)
                for prefix in blacklist_prefixes
            )
            and not any(
                substring in (market.get("ticker") or "")
                for substring in blacklist_substrings
            )
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

        # Opcional: si hay suficientes mercados “activos”, nos quedamos con los más activos
        min_active = int(os.getenv("KALSHI_MIN_ACTIVE", "50"))
        max_tickers = int(os.getenv("KALSHI_MAX_TICKERS", "300"))

        if min_active > 0:
            for key in ("volume_24h", "volume", "open_interest"):
                active_markets = [m for m in markets if (m.get(key) or 0) > 0]
                if len(active_markets) >= min_active:
                    markets = sorted(
                        active_markets, key=lambda m: (m.get(key) or 0), reverse=True
                    )
                    break

        # ------------------------------------------------------------
        # BUILD LIST OF REAL TRADEABLE TICKERS (EXPAND MVE -> LEGS)
        # ------------------------------------------------------------
        tickers_to_fetch: list[str] = []
        seen: set[str] = set()

        for market in markets:
            ticker = market.get("ticker") or ""
            if not ticker:
                continue

            if _is_mve_ticker(ticker):
                legs = market.get("mve_selected_legs") or []
                for leg in legs:
                    leg_ticker = leg.get("market_ticker") or ""
                    if not leg_ticker:
                        continue
                    if leg_ticker in seen:
                        continue
                    tickers_to_fetch.append(leg_ticker)
                    seen.add(leg_ticker)
                continue

            if ticker not in seen:
                tickers_to_fetch.append(ticker)
                seen.add(ticker)

        # ------------------------------------------------------------
        # SNAPSHOT FETCH LOOP
        # ------------------------------------------------------------
        require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") == "1"
        min_liq = float(os.getenv("KALSHI_MIN_LIQ", "1"))

        total_tickers = 0
        fetched_ok = 0
        fetch_errors = 0
        no_asks_both_sides = 0
        one_sided_only = 0
        two_sided = 0

        for ticker in tickers_to_fetch:
            if total_tickers >= max_tickers:
                break
            total_tickers += 1

            try:
                top = client.fetch_top_of_book(ticker)
            except Exception:
                fetch_errors += 1
                continue

            fetched_ok += 1

            has_yes_ask = top.yes_ask is not None
            has_no_ask = top.no_ask is not None

            # Si no hay asks en ningún lado, no podemos pricear
            if not has_yes_ask and not has_no_ask:
                no_asks_both_sides += 1
                continue

            if has_yes_ask and has_no_ask:
                two_sided += 1
            else:
                one_sided_only += 1

            # Si exiges 2-sided, descarta lo que no tenga ambas asks
            if require_two_sided and not (has_yes_ask and has_no_ask):
                continue

            yes_size = float(top.yes_ask_qty or 0)
            no_size = float(top.no_ask_qty or 0)

            # Si hay 2-sided, aplica filtro de liquidez mínimo (qty)
            if has_yes_ask and has_no_ask and min(yes_size, no_size) < min_liq:
                continue

            # Convert cents -> probability
            yes_px = float(top.yes_ask) / 100.0 if top.yes_ask is not None else 0.0
            no_px = float(top.no_ask) / 100.0 if top.no_ask is not None else 0.0

            snapshot = MarketSnapshot(
                market=Market(
                    venue=self.name(),
                    market_id=ticker,
                    question=ticker,
                    outcomes=("Yes", "No"),
                ),
                orderbook=OrderBookTop(
                    best_yes_price=yes_px,
                    best_yes_size=yes_size,
                    best_no_price=no_px,
                    best_no_size=no_size,
                ),
            )
            yield snapshot

        print(
            f"KalshiProvider stats: total={total_tickers} "
            f"ok={fetched_ok} errors={fetch_errors} "
            f"noasks={no_asks_both_sides} "
            f"one_sided={one_sided_only} two_sided={two_sided}"
        )
