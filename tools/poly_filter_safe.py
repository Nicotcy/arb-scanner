from __future__ import annotations

import argparse
import json
import re
from typing import Any


BAD_SPORTS = re.compile(r"\b(nfl|nba|mlb|nhl|super bowl|champions|real madrid|barcelona|injury|injured|vs\.?|match|game)\b", re.I)
BAD_CELEB = re.compile(r"\b(grammy|oscars|oscar|celebrity|actor|actress|singer|rapper|gaga|taylor|kanye)\b", re.I)


def normalize_outcomes(outs: Any) -> Any:
    if isinstance(outs, str):
        s = outs.strip()
        if s.startswith("[") and s.endswith("]"):
            try:
                return json.loads(s)
            except Exception:
                return outs
    return outs


def is_yes_no(m: dict[str, Any]) -> bool:
    outs = normalize_outcomes(m.get("outcomes"))
    if isinstance(outs, list) and outs and isinstance(outs[0], str):
        s = {x.strip().lower() for x in outs if isinstance(x, str)}
        return s == {"yes", "no"}
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="outp", required=True)
    ap.add_argument("--allow-celeb", action="store_true")
    ap.add_argument("--allow-sports", action="store_true")
    args = ap.parse_args()

    data = json.load(open(args.inp, "r", encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("Input must be a JSON list")

    out = []
    for m in data:
        if not isinstance(m, dict):
            continue
        q = (m.get("question") or "")
        if not q:
            continue
        if (not args.allow_sports) and BAD_SPORTS.search(q):
            continue
        if (not args.allow_celeb) and BAD_CELEB.search(q):
            continue
        if not is_yes_no(m):
            continue
        mm = dict(m)
        mm["outcomes"] = normalize_outcomes(mm.get("outcomes"))
        out.append(mm)

    json.dump(out, open(args.outp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"TOTAL: {len(data)}")
    print(f"SAFE:  {len(out)} -> {args.outp}")
    for m in out[:10]:
        print("-", m.get("slug"), "|", (m.get("question") or "")[:90])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
