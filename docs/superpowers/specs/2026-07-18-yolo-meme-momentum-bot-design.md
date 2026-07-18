# YOLO — Meme Coin Momentum Bot: Design Spec

**Date:** 2026-07-18
**Status:** Approved by Austin (pending final spec review)
**Repo:** https://github.com/asandler2727-coder/yolo

## 1. Goal

An automated bot that trades meme coins on Kraken with a momentum strategy, aiming for
short-term profit with a deliberately aggressive (but capped) risk posture. Claude builds the
code; the code executes trades; Austin owns the on/off switch and the go-live decision.

## 2. Background — lessons from the predecessor (`~/freqtrade`)

The prior "AI Trading Company" project died in April 2026. Autopsy findings that shape this
design:

- **The strategy never fired.** `CombinedBinHAndCluc` made zero trades in 11 days of dry-run.
  A minimum signal-frequency requirement is therefore a first-class acceptance criterion here.
- **Wrong universe.** It traded BTC/ETH/SOL/XRP majors — structurally incapable of the
  intended risk/reward. This project trades meme coins only.
- **Machinery sprawl.** Multi-agent LLM review boards, vector DBs, observability servers,
  FreqAI, and a 67-strategy zoo were built before anything traded. This project is one
  strategy, two configs, and one small sentiment add-on. Nothing else.
- **Open-ended dry-run.** "Dry-run until further notice" had no exit criteria and killed
  momentum. All validation gates here are time-boxed with explicit pass/fail rules.
- **Stale asset claims.** The "2.5 years of OKX US data" recorded in the old AGENTS.md does
  not exist (actual data: majors at 1d/4h only). Fresh 15m meme-pair data must be downloaded;
  nothing is migrated from the old repo.

Carried forward unchanged: the old project's security hard rules (§8) and the
Freqtrade + Kraken platform decision.

## 3. Architecture

- **Engine:** Freqtrade (stable Docker image), spot trading only, long only.
- **Exchange:** Kraken (Austin has an account; currently unfunded).
- **Machines:** developed on the Mac; runs 24/7 in Docker Desktop on the Windows 11 desktop
  (i9-14900K). Deployment = `git pull` + `docker compose up -d` on the PC.
- **Configs:**
  - `config-paper.json` — `dry_run: true`, committed to git, no secrets.
  - `config-live.json` — real keys, gitignored, created only after the dry-run gate passes.
- **Monitoring:** FreqUI (Freqtrade's local web dashboard) on the Windows box; optional
  Telegram notifications (decide during implementation).
- **Repo:** private GitHub `asandler2727-coder/yolo`; keys live only in gitignored files on
  the machine that runs the bot.

## 4. Trading universe

Kraken meme coins quoted in **USD** (not USDT — Kraken's meme liquidity is on USD pairs).
Target list, to be confirmed against Kraken's live tradeable pairs during implementation:

`DOGE/USD, SHIB/USD, PEPE/USD, BONK/USD, WIF/USD, FLOKI/USD`

Static whitelist in v1. Phase 2 (§7) rotates it based on X sentiment. Coins Austin already
holds personally are never added to the whitelist (carried hard rule).

## 5. Strategy — `MemeMomentum`

Timeframe: **15m candles**. Long-only spot momentum:

- **Entry:** price change over the last N candles exceeds X% AND current volume is running
  well above its rolling average (volume spike confirms the move is real, not drift). Exact
  N, X, and volume multiplier are set by backtesting, not chosen by feel.
- **Exits (three layers, all Freqtrade-native):**
  1. Hard stop-loss: worst-case per-trade loss in the −5% to −8% range (tuned in backtest).
  2. Trailing stop: activates once a trade is meaningfully in profit, locks in gains as the
     pump fades.
  3. Time-based exit: a trade that goes nowhere for a set number of hours is closed to free
     the slot.
- **No other indicators in v1.** Momentum + volume only, so results are attributable.

### Minimum-aggression requirement (hard acceptance criterion)

The tuned strategy must produce **≥ 5 trades/week on average in backtest** across the
whitelist. Below that bar, it gets retuned before it ever reaches dry-run. During dry-run and
live operation, **zero trades in any 48h window while markets are open is treated as a fault**
to investigate the same day, not a curiosity.

## 6. Risk guardrails (hard-coded)

- **Bankroll cap:** $750 total. `max_open_trades: 3`, fixed stake $250/trade. The bot cannot
  deploy more than the cap.
- **Freqtrade protections (never disabled):**
  - `CooldownPeriod` — no immediate re-entry after a stop-loss.
  - `StoplossGuard` — halts trading after a burst of consecutive stop-loss hits.
  - `MaxDrawdownProtection` — full stop if total drawdown exceeds ~15%; requires human restart.
- **Kill switches:** stop button in FreqUI; `docker compose down` on the PC.
- **Live starts at half stakes** ($125/trade) for the first two weeks of live operation.

## 7. Phase 2 — Sentiment Whitelist Advisor (Grok / X)

Social sentiment picks the menu; momentum pulls the trigger. Sentiment never touches entry or
exit logic (it is not backtestable and would poison the strategy's testability).

- A scheduled job (1–2×/day) runs a Grok X-sentiment scan (`whathappened`-style analysis) over
  the meme coin space and writes a short report plus a proposed whitelist (ranked by X heat,
  filtered to Kraken-tradeable pairs) into the repo.
- **Advisory mode first:** Austin (or a one-command apply step) accepts the proposed whitelist.
  If its picks prove sensible across the dry-run period, it graduates to rotating the
  whitelist automatically.
- Built only after v1's backtest → dry-run pipeline is running. It is one small script + one
  schedule, not an orchestrator.

## 8. Security hard rules (carried from predecessor, non-negotiable)

1. Rotate Kraken API keys before funding the account — the old keys were once shared in chat
   and were never rotated.
2. API keys get **no withdrawal or transfer permissions**, ever.
3. Keys never appear in git, prompts, or chat. Gitignored config / `.env` only.
4. Live trading is enabled only when Austin explicitly says **"I am ready to go live."**
5. Circuit breakers (§6) are never removed or disabled, in any mode.
6. Austin's personal holdings never go on the bot's whitelist.

## 9. Validation gates (time-boxed, explicit)

1. **Backtest gate:** fresh 15m data for the whitelist downloaded (Kraken via trades download,
   or another US-accessible source with proper 15m spot history — resolved during
   implementation). Strategy tuned until it meets: ≥5 trades/week, positive expectancy after
   Kraken taker fees, max drawdown within tolerance. Results recorded in the repo.
2. **Dry-run gate: exactly 2 weeks** of paper trading on the Windows box, then a decision —
   no extensions by default. Pass = the bot actually fired at a healthy rate AND beat holding
   cash after fees. Fail = retune, restart the 2-week clock.
3. **Go-live:** on Austin's explicit phrase only, at half stakes for 2 weeks, then full stakes
   ($750 cap) if nothing alarming.

## 10. Testing & verification

- Backtests are reproducible: pinned Freqtrade version, committed strategy + config, recorded
  data range and results in the repo.
- A smoke test verifies the strategy file loads and produces entry signals on known historical
  data (guards against the silent zero-trade failure mode).
- Dry-run health is observed on the real surface: FreqUI showing live signal evaluation and
  paper trades, checked daily during the 2-week window.

## 11. Out of scope (deliberately)

Multi-agent review boards, FreqAI/ML models, vector databases, observability servers,
strategy zoos, short selling, margin/futures, DEX/on-chain trading, and any autonomous
increase of stakes or risk limits. If v1 makes money, scope grows one small step at a time.
