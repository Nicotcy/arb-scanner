# External analysis notes (pmxt + prediction-market-arbitrage-bot)

> ⚠️ This environment blocks outbound GitHub access, so I could not fetch the upstream repositories here.
> The notes below describe **where to look** once you clone the repos locally on your Mac.

## pmxt (Polymarket SDK)

1. Clone or install the library:
   ```bash
   git clone https://github.com/Polymarket/pmxt.git
   ```
2. Search for market + orderbook clients:
   ```bash
   rg "market|orderbook|order book" pmxt
   ```
3. Look for:
   - Client modules that expose REST/WebSocket calls for markets and orderbooks.
   - Data models (Pydantic/dataclasses) that represent markets and books.
4. Credentials are typically handled in configuration modules or client constructors (look for API key or signer parameters). Search for:
   ```bash
   rg "api_key|private|secret|wallet|auth|signature" pmxt
   ```

## realfishsam/prediction-market-arbitrage-bot

1. Clone the repo:
   ```bash
   git clone https://github.com/realfishsam/prediction-market-arbitrage-bot.git
   ```
2. Find market + orderbook wiring:
   ```bash
   rg "market|orderbook|order book" prediction-market-arbitrage-bot
   ```
3. Find credential handling / secrets:
   ```bash
   rg "api_key|secret|private|wallet|auth" prediction-market-arbitrage-bot
   ```

Once those files are identified, map the relevant calls into `arb_scanner/sources/polymarket.py` and `arb_scanner/sources/kalshi.py`.
