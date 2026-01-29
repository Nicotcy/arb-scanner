# arb-scanner

Read-only scanner (no trading) for Kalshi + Polymarket. The default workflow keeps `DRY_RUN=1` and uses stub data until you wire real APIs.

## Quick start (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 scanner.py --use-stub
```

### Environment flags

```bash
export DRY_RUN=1          # enforced default; scanner exits if set to 0
export ALERT_ONLY=0       # set to 1 to print only opportunities above threshold
export ALERT_THRESHOLD=0.02
export FEE_BUFFER_BPS=25  # fee + slippage buffer
```

### ALERT_ONLY example

```bash
export ALERT_ONLY=1
export ALERT_THRESHOLD=0.02
python3 scanner.py --use-stub
```

## Output fields

Each candidate prints:

- `market_pair`
- `best_yes_price_A`
- `best_no_price_B`
- `hedge_cost`
- `estimated_fees` (buffered)
- `top_of_book_liquidity`
- `market_mismatch` (flagged when not pure YES/NO)
- `net_edge`

## External reference analysis

See `docs/external_analysis.md` for notes on how to inspect `pmxt` and `realfishsam/prediction-market-arbitrage-bot` for market/orderbook modules and credential handling.
