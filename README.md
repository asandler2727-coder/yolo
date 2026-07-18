# YOLO — Meme Coin Momentum Bot

An automated trading bot built on [Freqtrade](https://www.freqtrade.io/). It scans the whole
Kraken USD market for trending, high-volume coins and trades them with a price/volume momentum
strategy. Austin owns the on/off switch; the code does the trading.

**Status:** design phase — see the spec in `docs/superpowers/specs/`.

## The rules this project lives by

1. Backtest first, then 2 weeks of paper trading (dry-run), then — only on Austin's explicit
   "I am ready to go live" — real money at half stakes.
2. Hard-coded risk cap: $750 total, max 3 positions of $250, automatic halt at 15% drawdown.
3. A strategy that doesn't fire at least ~5 trades/week in backtest gets retuned, not deployed.
   Zero-trade limbo killed the last project; it is an automatic failure condition here.
4. Kraken API keys: no withdrawal permissions, never committed to git, rotated before funding.
5. The circuit breakers (stop-loss guard, max drawdown halt) are never disabled.

## Layout

- `user_data/strategies/` — the Freqtrade strategy (the only "smart" code here)
- `config-paper.json` — dry-run config (real market data, fake money)
- `config-live.json` — live config; gitignored, created only after the dry-run gate passes
- `docs/superpowers/specs/` — design specs

## Running it

Runs via Docker (Docker Desktop on the Windows box). Exact commands land here once the
implementation exists.

Predecessor: `~/freqtrade` (the "AI Trading Company" project) — retired; its autopsy is
summarized in the spec.
