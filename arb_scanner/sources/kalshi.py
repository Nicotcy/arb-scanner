"""Kalshi market data provider (read-only via public API)."""

from __future__ import annotations

from collections.abc import Iterable
import os

from arb_scanner.kalshi_public import KalshiPublicClient, normalize_kalshi_price
from arb_scanner.models import Market, MarketSnapshot, OrderBookTop
from arb_scanner.sources.base import MarketDataProvider

    def __init__(self) -> None:
        self.client = KalshiPublicClient()

    def name(self) -> str:
        return "Kalshi"

    def fetch_market_snapshots(self) -> Iterable[MarketSnapshot]:
        # Paging del listado
        max_pages = int(os.getenv("KALSHI_PAGES", "5"))
        limit_per_page = int(os.getenv("KALSHI_LIMIT", "200"))

        markets = list(
            self.client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page)
        )

        markets_raw = markets

        # Blacklist para reducir ruido (especialmente MVEs deportivos gigantes)
        blacklist_prefixes = ("KXMVE", "KXMVESPORTS")
        blacklist_substrings = ("MULTIGAMEEXTENDED",)

        markets_filtered = [
            market
            for market in markets
            if not any((market.get("ticker") or "").startswith(prefix) for prefix in blacklist_prefixes)
            and not any(sub in (market.get("ticker") or "") for sub in blacklist_substrings)
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

        # Filtrado por actividad (si quieres)
        min_active = int(os.getenv("KALSHI_MIN_ACTIVE", "50"))
        max_tickers = int(os.getenv("KALSHI_MAX_TICKERS", "300"))

        for key in ("volume_24h", "volume", "open_interest"):
            active_markets = [m for m in markets if (m.get(key) or 0) > 0]
            if len(active_markets) >= min_active:
                markets = sorted(active_markets, key=lambda m: m.get(key) or 0, reverse=True)
                break

        # 1) Construimos lista de tickers tradeables:
        #    - Si es MVE, usamos sus legs (market_ticker)
        #    - Si no, usamos su ticker normal
        tickers_to_fetch: list[str] = []
        seen: set[str] = set()

        for market in markets:
            t = market.get("ticker")
            if not t:
                continue

            legs = market.get("mve_selected_legs") or []
            if legs:
                for leg in legs:
                    leg_ticker = leg.get("market_ticker")
                    if leg_ticker and leg_ticker not in seen:
                        tickers_to_fetch.append(leg_ticker)
                        seen.add(leg_ticker)
            else:
                if t not in seen:
                    tickers_to_fetch.append(t)
                    seen.add(t)

        # 2) Snapshot fetch loop vía orderbook top
        require_two_sided = os.getenv("KALSHI_REQUIRE_TWO_SIDED", "1") == "1"
        min_liq = float(os.getenv("KALSHI_MIN_LIQ", "1"))

        total = 0
        ok = 0
        fetch_errors = 0
        noprices = 0
        liqskip = 0
        one_sided = 0
        two_sided = 0

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

            # Si no hay precios, fuera
            if not has_yes and not has_no:
                noprices += 1
                continue

            # Si exiges dos lados, y falta uno, fuera
            if require_two_sided and not (has_yes and has_no):
                one_sided += 1
                continue

            yes_size = float(top.yes_ask_qty or 0)
            no_size = float(top.no_ask_qty or 0)

            # Si hay ambos lados, imponemos liquidez mínima top-of-book
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

        print(
            "KalshiProvider stats: "
            f"total={total} ok={ok} errors={fetch_errors} "
            f"noprices={noprices} liqskip={liqskip} "
            f"one_sided={one_sided} two_sided={two_sided}"
        )
