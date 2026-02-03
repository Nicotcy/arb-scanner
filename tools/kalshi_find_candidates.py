from __future__ import annotations

"""Find likely Kalshi tickers for a list of Polymarket markets.

Bootstrap workflow:
  1) Generate a Polymarket shortlist (slug + question), e.g.:
       python tools/poly_list_active.py --limit 200 --min-liquidity 2000 > /tmp/poly_active.json

  2) Rank Kalshi candidates for each Polymarket question:
       python tools/kalshi_find_candidates.py --poly-json /tmp/poly_active.json --top 8 --refresh-kalshi

It will:
  - Fetch & cache the current open Kalshi market list (ticker + text fields)
  - For each Polymarket question, compute similarity scores vs Kalshi questions
  - Print top-N candidates + optionally write JSON for review

Design notes:
  - Uses a simple, explainable score (SequenceMatcher + token Jaccard).
  - Keeps caching on disk to avoid hammering Kalshi when you iterate.
  - Does NOT attempt to "auto-map". Human validation stays in the loop.
"""

import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher
from typing import Any


RE_PUNCT = re.compile(r"[^a-z0-9\s]+", re.IGNORECASE)


def _norm(text: str) -> str:
    text = (text or "").lower().strip()
    text = RE_PUNCT.sub(" ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _tokens(text: str) -> set[str]:
    t = _norm(text)
    stop = {
        "will", "the", "a", "an", "to", "of", "in", "on", "for", "by", "and", "or",
        "be", "is", "are", "was", "were", "at", "before", "after", "this", "that", "it", "as",
    }
    return {x for x in t.split(" ") if x and x not in stop and len(x) >= 3}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _score(poly_q: str, kal_text: str) -> float:
    a = _norm(poly_q)
    b = _norm(kal_text)
    if not a or not b:
        return 0.0
    seq = SequenceMatcher(None, a, b).ratio()
    jac = _jaccard(_tokens(a), _tokens(b))
    return 0.65 * seq + 0.35 * jac


def load_poly_list(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"poly-json must be a JSON list, got {type(data).__name__}")
    out: list[dict[str, Any]] = []
    for m in data:
        if not isinstance(m, dict):
            continue
        slug = (m.get("slug") or "").strip()
        q = (m.get("question") or "").strip()
        outcomes = m.get("outcomes")
        if not slug or not q:
            continue
        out.append({"slug": slug, "question": q, "outcomes": outcomes, "liquidityNum": m.get("liquidityNum")})
    return out


def _kalshi_market_text(m: dict[str, Any]) -> tuple[str, str]:
    ticker = (m.get("ticker") or "").strip()
    parts: list[str] = []
    for k in ("title", "question", "subtitle", "event_title", "series_title"):
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return ticker, " | ".join(parts)


def fetch_kalshi_open_markets(max_pages: int, limit_per_page: int) -> list[dict[str, Any]]:
    from arb_scanner.kalshi_public import KalshiPublicClient

    client = KalshiPublicClient()
    markets = list(client.list_open_markets(max_pages=max_pages, limit_per_page=limit_per_page))
    out: list[dict[str, Any]] = []
    for m in markets:
        if not isinstance(m, dict):
            continue
        ticker = (m.get("ticker") or "").strip()
        if not ticker:
            continue
        if ticker.upper().startswith("KXMVE"):
            continue
        out.append(m)
    return out


def load_or_refresh_kalshi_cache(cache_path: str, refresh: bool, max_pages: int, limit_per_page: int) -> list[dict[str, Any]]:
    if (not refresh) and os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data

    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    markets = fetch_kalshi_open_markets(max_pages=max_pages, limit_per_page=limit_per_page)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(markets, f, indent=2, ensure_ascii=False)
    return markets


def main() -> int:
    ap = argparse.ArgumentParser(description="Rank Kalshi ticker candidates for Polymarket slugs (bootstrap mapping)")
    ap.add_argument("--poly-json", default="/tmp/poly_active.json")
    ap.add_argument("--kalshi-cache", default="/tmp/kalshi_open.json")
    ap.add_argument("--refresh-kalshi", action="store_true")
    ap.add_argument("--top", type=int, default=8)
    ap.add_argument("--max-poly", type=int, default=0)
    ap.add_argument("--slug", default="")
    ap.add_argument("--out", default="/tmp/kalshi_candidates.json")
    ap.add_argument("--max-pages", type=int, default=int(os.getenv("KALSHI_CAND_MAX_PAGES", "6")))
    ap.add_argument("--limit-per-page", type=int, default=int(os.getenv("KALSHI_CAND_LIMIT", "200")))
    args = ap.parse_args()

    poly = load_poly_list(args.poly_json)
    if args.slug:
        poly = [m for m in poly if m.get("slug") == args.slug]
    if args.max_poly and args.max_poly > 0:
        poly = poly[: args.max_poly]
    if not poly:
        print("No Polymarket markets found to process.")
        return 2

    kalshi = load_or_refresh_kalshi_cache(args.kalshi_cache, args.refresh_kalshi, args.max_pages, args.limit_per_page)
    kal_texts: list[dict[str, Any]] = []
    for m in kalshi:
        t, txt = _kalshi_market_text(m)
        if not t or not txt:
            continue
        kal_texts.append({"ticker": t, "text": txt})

    results: list[dict[str, Any]] = []

    for i, pm in enumerate(poly, 1):
        slug = pm["slug"]
        pq = pm["question"]

        scored = []
        for km in kal_texts:
            s = _score(pq, km["text"])
            if s <= 0:
                continue
            scored.append((s, km["ticker"], km["text"]))

        scored.sort(reverse=True, key=lambda x: x[0])
        top = scored[: max(1, args.top)]

        print("=" * 100)
        print(f"[{i}/{len(poly)}] Poly: {slug}")
        print(f"Q: {pq}")
        print("Top Kalshi candidates:")
        for s, t, txt in top:
            print(f"  {s:0.3f}  {t:<18}  {txt[:120]}")

        results.append(
            {
                "polymarket": {
                    "slug": slug,
                    "question": pq,
                    "liquidityNum": pm.get("liquidityNum"),
                    "outcomes": pm.get("outcomes"),
                },
                "candidates": [{"score": float(s), "kalshi_ticker": t, "kalshi_text": txt} for (s, t, txt) in top],
            }
        )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print("=" * 100)
        print(f"Wrote: {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
