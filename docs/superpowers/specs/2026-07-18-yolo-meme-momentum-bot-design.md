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
- **Wrong universe.** It traded a fixed list of four majors (BTC/ETH/SOL/XRP) — structurally
  incapable of the intended risk/reward. This project dynamically hunts whatever is trending
  on high volume instead of any fixed list.
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

## 4. Trading universe — dynamic whole-market scan

Not a fixed coin list. The bot scans (nearly) the whole Kraken **USD-quoted** spot market and
trades whatever is trending, using Freqtrade's native dynamic pairlist chain:

1. **VolumePairList** — rank all Kraken USD pairs by quote volume, keep the top ~30.
2. **Movement filter** — of those, prefer pairs with meaningful recent price change /
   volatility (the "trending" part; exact filter tuned during implementation).
3. **Sanity filters** — drop pairs with wide spreads, ultra-low prices (bad fill precision),
   or thin liquidity. Trending-but-illiquid means terrible fills; those are excluded.
4. **Blacklist** — stablecoins and pegged/wrapped assets (USDT, USDC, DAI, EUR, WBTC, …),
   plus any coins Austin personally holds (carried hard rule; Austin supplies the holdings
   list at implementation time).

The refreshed list feeds the momentum strategy, which still makes every actual trade decision.
Majors like BTC/ETH may appear when they're genuinely the top movers — that's acceptable; the
scan follows the market's attention rather than a fixed meme menu.

**Backtesting note:** dynamic selection must also be applied historically (data downloaded for
the broad Kraken USD universe, volume/movement ranking computed from candles per period) so
backtests aren't biased by today's trending list — a look-ahead trap the implementation must
explicitly avoid.

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
scanned universe. Below that bar, it gets retuned before it ever reaches dry-run. During dry-run and
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
  the crypto space and writes a short report into the repo: which Kraken-tradeable coins X is
  heating up on, plus any the volume scan (§4) is watching that sentiment says are cooling.
- Its output can add sentiment-hot coins to the scan's candidate set or blacklist
  sentiment-dead ones — it adjusts *which pairs get watched*, never entries/exits.
- **Advisory mode first:** Austin (or a one-command apply step) accepts its suggestions. If
  its picks prove sensible across the dry-run period, it graduates to applying them
  automatically.
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
