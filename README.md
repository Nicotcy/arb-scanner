# Big-step patch (arb-scanner)

This is a *patch pack* you can copy into your existing repo.
It avoids "install/packaging" changes and focuses on a big productivity jump:

1) Polymarket outcomes normalization (Gamma sometimes returns outcomes as a JSON string).
2) A robust SAFE filter tool for Polymarket lists (outputs JSON with normalized outcomes list).
3) A SAFE/LAB mapping split with a single loader function (keeps backwards compatibility).
4) A slightly safer/portable kalshi_find_candidates (adds sys.path injection) + writes candidates JSON.

## How to apply (manual, simple)
From your repo root (where daemon.py lives), copy these files over, overwriting if prompted:

- tools/poly_list_active.py
- tools/poly_filter_safe.py
- arb_scanner/mappings.py
- tools/kalshi_find_candidates.py  (optional if you already have it; mine includes portability tweaks)

## Quick smoke flow
1) Produce active markets:
   python3 tools/poly_list_active.py --limit 500 --min-liquidity 500 > /tmp/poly_active.json

2) Make SAFE shortlist:
   python3 tools/poly_filter_safe.py --in /tmp/poly_active.json --out /tmp/poly_active_safe.json

3) Find Kalshi candidates:
   python3 tools/kalshi_find_candidates.py --poly-json /tmp/poly_active_safe.json --top 8 --max-poly 20 --refresh-kalshi

4) Add a few mappings into:
   arb_scanner/mappings.py  (SAFE_MAPPINGS or LAB_MAPPINGS)

5) Run daemon:
   python3 daemon.py --use-kalshi --use-mapping --mode lab
   python3 daemon.py --use-kalshi --use-mapping --mode safe

## Rollback
Because this is just file copy, rollback is "git checkout" or restore from your previous folder.
