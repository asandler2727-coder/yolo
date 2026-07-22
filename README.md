# YOLO — Meme Coin Momentum Bot

An experimental Kraken/Freqtrade research project for trending, high-volume USD coins.
Austin owns the on/off switch; no strategy is allowed to paper trade or trade real money
without passing the project's research gates.

**Status: research only.** Family A and Family B are retired. There is no approved paper
strategy and no live strategy. The Docker launcher is deliberately blocked by default.

## The rules this project lives by

1. Backtest first, then 2 weeks of paper trading (dry-run), then — only on Austin's explicit
   "I am ready to go live" — real money at half stakes.
2. Intended risk cap: $750 total. Position sizing and circuit-breaker behavior must be
   container-verified for any future approved strategy before its paper clock starts.
3. Frequency gate: ≥5 trades/week **in up-regime periods**; sitting out bears is allowed.
   Positive profit after ~0.4% taker fees is still required. v1-style churn is not the goal.
4. Kraken API keys: no withdrawal permissions, never committed to git, rotated before funding.
5. The circuit breakers (stop-loss guard, max drawdown halt) are never disabled.

## Layout

- `user_data/strategies/` — the Freqtrade strategy (the only "smart" code here)
- `config-paper.json` — dry-run config (real market data, fake money)
- `config-live.json` — live config; gitignored, created only after the dry-run gate passes
- `docs/superpowers/specs/` — design specs

## Running it

Do **not** start Docker or paper trading yet. The checked-in `MemeMomentum` strategy is the
retired Family A implementation; it is retained as research evidence, not an approval to run.
`config-paper.json` stays in dry-run mode and starts stopped, while the Compose launcher also
refuses to run unless a future approval is recorded deliberately.

Windows preparation notes are in [docs/DEPLOY-WINDOWS.md](docs/DEPLOY-WINDOWS.md), but its
launch steps remain blocked until a strategy passes research review and Austin explicitly
approves the paper run.

Predecessor: `~/freqtrade` (the "AI Trading Company" project) — retired; its autopsy is
summarized in the spec.

## Versions

The Compose file currently references `freqtradeorg/freqtrade:stable`; pin and verify an exact
image before any future paper approval so behavior cannot drift between runs.
