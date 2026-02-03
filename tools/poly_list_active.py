from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--category", type=str, default="")
    ap.add_argument("--min-liquidity", type=float, default=1000.0)
    args = ap.parse_args()

    url = "https://gamma-api.polymarket.com/markets"
    params = {
        "limit": args.limit,
        "active": "true",
        "closed": "false",
        "archived": "false",
        "order": "liquidityNum",
        "ascending": "false",
    }
    if args.category:
        params["category"] = args.category

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data: list[dict[str, Any]] = r.json()

    out = []
    for m in data:
        liq = float(m.get("liquidityNum") or 0.0)
        if liq < args.min_liquidity:
            continue
        slug = m.get("slug")
        q = m.get("question")
        outcomes = m.get("outcomes")
        out.append(
            {
                "slug": slug,
                "liquidityNum": liq,
                "question": q,
                "outcomes": outcomes,
            }
        )

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
