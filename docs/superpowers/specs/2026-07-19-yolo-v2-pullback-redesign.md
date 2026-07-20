# YOLO v2 redesign — trend-filtered pullback (primary) + tabled families

**Date:** 2026-07-19  
**Status:** Approved direction by Austin; this document is the redesign brief for implementation  
**Amended 2026-07-20:** entry *pricing* (market → resting limit −2%) is amended by
`2026-07-20-yolo-b-prime-limit-entry.md` after the audited exit-path analysis; that file
wins on entry pricing. Signals, exits, gate, and everything else here stand.  
**Repo:** https://github.com/asandler2727-coder/yolo  
**Supersedes:** MemeMomentum **v1** entry/exit hypothesis in the 2026-07-18 design spec §5  
**Does not supersede:** §6 risk guardrails, §8 security rules, architecture (§3), universe (§4), sentiment phase (§7)

---

## 1. Why v1 is frozen

v1 entry: *price already up ≥X% over N×15m candles + volume spike* → buy the chase.

Evidence (`docs/backtests.md`, Task 6 sweep, `docs/design-critique-2026-07-19.md`):

- Negative per-trade expectancy on Feb–Mar 2026 full-universe data at `--fee 0.004`.
- Stricter entry params only reduced *how often* money was lost — classic no-edge signature.
- ~0.8% round-trip taker fees dominate small 15m continuations after a completed pump.
- Regime-blind longs amplified a bear window (strategy ~5× market loss).

**Do not retune v1.** Implement **one** new primary hypothesis below. Tabled families stay off the critical path until the primary is judged.

---

## 2. Primary hypothesis (build this)

### Name

**`MemeMomentum` v2 — higher-TF uptrend + 15m pullback entry**  
(keep class name `MemeMomentum` so configs/Docker stay stable; rewrite signals under the hood.)

### One-sentence edge claim

In an up regime, buying a *pullback* toward short-term support on a still-liquid pair has better fee-adjusted expectancy than buying *after* a completed 15m pump.

### Timeframes

| Role | TF | Purpose |
|---|---|---|
| Regime | **1h** (informative; see implement note) | Allow longs only when market/pair trend is up |
| Entry / exit management | **15m** | Pullback trigger, volume check, stops/ROI |

**Freqtrade note:** primary candle stream stays `timeframe = "15m"`. Regime uses either (a) informative 1h pair(s) via `@informative` / `merge_informative_pair`, or (b) 1h-equivalent computed from 15m (e.g. EMA on 4× resampled bars). Prefer (a) for BTC regime if pair data is available; pure-pandas unit tests can use resampled synthetic 1h.

### Regime filter (must pass before any long)

**Primary regime source:** BTC/USD (or BTC/USDT if the live quote is USDT — use the Kraken pair actually in the data set; document the choice in code comments).

**Rule (starting defaults — one small knobs set only after first green baseline is impossible):**

1. BTC 1h close **>** EMA(50) on 1h, **and**
2. BTC 1h EMA(20) **>** EMA(50) (trend not rolling over).

If regime fails → **no entries** (zero trades that period is acceptable under the amended gate).

**Optional pair-level confirm (include in v2.0):** traded pair 15m close **>** EMA(50) on 15m so we do not long a coin already in free-fall inside a BTC up day. If this kills frequency too hard in first backtest, drop pair-EMA first — **never** drop BTC regime first.

### Entry (pullback — not chase)

All must be true on the **15m** bar that fires:

1. **Regime OK** (above).
2. **Prior impulse exists:** pair made a meaningful advance in the recent window without requiring “buy the top of it”:
   - Highest close in last `impulse_lookback` candles (default **12** = 3h) is ≥ `impulse_min_pct` (default **+4%**) above the lowest close in that same window.
   - Purpose: we only pullback-buy coins that *had* a real move, not dead chop.
3. **Pullback in progress (non-chase):**
   - Current close is **below** the high of the last `impulse_lookback` candles by at least `pullback_min_pct` (default **1.5%**), **and**
   - Current close is within `pullback_max_pct` (default **5%**) of that high (not a full trend failure).
   - **OR** (equivalent structure preferred if easier to code cleanly): close is between EMA(20) and EMA(50) on 15m after having been above EMA(20). Pick **one** formulation in code; do not OR both without tests.
4. **Volume still alive:** current volume ≥ `volume_mult` × rolling average (defaults: mult **1.5**, window **48**). Lower mult than v1 (2.0) because we are not demanding a climax spike at the top.
5. **Anti-chase hard block:** `pct_change` over last **3** candles (45m) must be **<** `chase_block_pct` (default **+2%**). If the last 45m already ripped, do not buy.

**Explicit non-goals for entry:** no RSI stack, no MACD, no Bollinger width zoo, no sentiment in entry.

### Exits (fee-aware)

Assume ~0.8% round-trip taker; targets must clear that with room for slippage.

| Layer | Starting rule | Notes |
|---|---|---|
| Hard stop | `stoploss = -0.04` **or** ATR(14)×1.5 under entry, capped at −6% | Prefer structure: stop under pullback swing low if implementable in `custom_stoploss`; else fixed −4% first ship |
| ROI ladder | `{0: 0.03, 60: 0.02, 180: 0.01}` | ~3% first target, not v1’s 10% after a spent pump |
| Trailing | `trailing_stop_positive = 0.012`, offset `0.02`, only after offset | Locks small winners |
| Stagnation | Close if open **> 6 hours** and profit **< 1%** | Shorter than v1’s 12h |
| Signal exit | Optional: exit if regime flips off for 2 consecutive 1h bars | Nice-to-have after core works |

### Protections / bankroll

**Unchanged from spec §6:** CooldownPeriod, StoplossGuard, MaxDrawdown ~15%, $750 / 3×$250, never weakened.

### Amended backtest gate (stricter on quality, not looser on profit)

| Leg | Rule |
|---|---|
| Profit | **Positive total profit** at `--fee 0.004` on the rolling harness windows used for the decision |
| Frequency | **≥5 trades/week average only during up-regime periods** (months/windows where BTC regime filter is true for a material share of bars). Zero-trade **down-regime** months are **acceptable** and do **not** fail the frequency leg |
| Drawdown | Still respect MaxDrawdown protection; report max DD; no automatic pass if DD is catastrophic even with positive total profit — flag for Austin if max DD > ~25% on a month |

Never loosen profit or fee assumptions. Never disable protections in the harness.

### Validation path

1. Freeze v1 sweeps.
2. Implement pure-pandas signals + tests (TDD).
3. Wire strategy; keep protections.
4. Rerun **control** baseline on Feb–Mar with protections + $250k floor (expect v1 still bad; documents comparability).
5. Run **v2** on Feb–Mar **in-sample** (expect fewer trades; may still struggle if Feb–Mar is mostly down-regime — that is OK if the bot largely sits out and does not destroy capital).
6. When Apr–Jul data is complete → **out-of-sample only** for v2. Not a lottery ticket for v1.

### Code layout (preserve project discipline)

| File | Role |
|---|---|
| `user_data/strategies/momentum_signals.py` | Pure pandas: indicators + `entry_mask` (+ optional `regime_mask`). Unit-tested, no freqtrade imports |
| `user_data/strategies/MemeMomentum.py` | Freqtrade IStrategy: informative merge, ROI/stop/trail/stagnation, protections |
| `tests/test_momentum_signals.py` | Expand for pullback + regime + anti-chase cases |
| `scripts/rolling_backtest.py` | Keep ranking floor + `--enable-protections`; no strategy zoo |

**Params:** one `DEFAULT_PARAMS` dict. No multi-knob grid search until a single default set shows non-negative expectancy on in-sample *or* clearly sits out bears without large losses. If defaults fail, change **one** conceptual knob (e.g. pullback depth), not a 9-cell sweep of hope.

---

## 3. Tabled strategy families (do not build yet)

These are the other starting points discussed with Austin. **Status: tabled.** Revisit only if primary fails after a honest OOS attempt, or Austin prioritizes a different product bet.

| ID | Family | Core idea | When it might beat primary | Main risks on this stack | Revisit trigger |
|---|---|---|---|---|---|
| **A** | Range breakout + volume | Enter when price breaks a multi-bar range high **with** volume ≥1.5–2× avg; optional retest entry | Strong trending months; memes that coil then run | Late breakouts + fees; fakeouts in chop; easy to recreate v1 chase if range is defined as “already up 3%” | Primary sits out forever or misses all real pumps even in up-regime |
| **B** | Mean-reversion / fade pump | After parabolic 15–30m extension, fade toward VWAP/mid when momentum dies | High-vol mean-reverting coins; good books | Thin meme books gap through stops; short-like risk on spot longs (bounce fails → bleed); fee-sensitive small targets | Primary works on majors but fails on meme tails and Austin wants fade experiments |
| **C** | Session / liquidity scalps | Trade only high-liquidity hours (e.g. US cash open); focus BTC/ETH first, port later | Improving fill quality; reducing dead-session noise | Misses 24/7 meme catalysts; needs session clock + pair policy changes | Fills/spreads dominate even when signals look good in OHLC backtests |
| **D** | (Rejected pattern) v1 chase-pump | Buy completed % move + climax volume | — | **Proven negative expectancy** here | **Never revisit as primary** |

**Rules for tabled work:**

- No parallel implementation of A/B/C while v2 primary is unfinished.
- No 67-strategy zoo (spec §11).
- If primary fails OOS with good process, pick **one** tabled family via a new short redesign note — do not combine A+B+C.

---

## 4. Product behavior changes Austin already approved

1. Bot may **sit idle in bear regimes** (zero trades OK).
2. Frequency gate is **conditional on up-regime**, not calendar-blind.
3. Fewer trades with fee-aware targets preferred over high churn.
4. Spec §6/§8 money and safety rules stay hard.

---

## 5. Success criteria for “redesign done” (docs) vs “strategy viable” (code)

| Milestone | Done means |
|---|---|
| Redesign docs | This file + design-spec §5/§9 amended + plan + handoff for implementer |
| Implementation | Tests for new signals green; strategy loads; rolling harness runs v2 |
| Viable candidate | Amended gate pass on in-sample **and** OOS (Apr–Jul when data ready); DD not catastrophic |
| Dry-run eligible | Viable candidate + Austin still wants paper; then 2-week dry-run per §9 |

---

## 6. Explicit non-goals (still)

Shorting, margin/futures, FreqAI, multi-agent entry boards, sentiment-driven entries, maker-fee fantasy without re-gating fills, and any raise of the $750 cap without Austin.
