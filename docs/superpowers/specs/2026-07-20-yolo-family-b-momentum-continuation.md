# YOLO family B — momentum continuation above structure, two universe arms

**Date:** 2026-07-20
**Status:** DRAFT v1 — not yet audited, awaiting research-auditor pass and then
Austin's spec-review gate. **No code, no signal work, no runs before his approval.**
**Opens:** family A retired 2026-07-20 after 3 of 15 dev iterations — every cell
decisively negative, gross expectancy ≈ 0 on both arms (`docs/family-a-post-mortem.md`).
**Still governs:** master spec §6 risk guardrails and §8 security rules; v2 brief regime
filter; the amended gate shape; sizing 10% of equity per trade, max 10 open; `dry_run`
stays true; protections never weakened.

---

## 1. What is new here

1. **New entry premise.** Family A bought breakouts *at* the range edge and measured
   zero gross edge. Its one hypothesis-grade positive signal ran the other way: the
   entries most extended above the range (1.0–1.5%, the band its anti-chase cap nearly
   refused) lost least — −0.25% net, positive gross of fees, on a monotone gradient
   (n=135, in-sample). Family B tests that extrapolation directly: enter *after* the
   move has confirmed, inside a bounded band above structure, and hold for multi-day
   continuation.
2. **New protocol stage: a gross-edge kill gate (phase 0) before any iteration.**
   Family A's post-mortem lesson #1: one entry-only diagnostic would have killed it at
   zero cost. Family B cannot spend a single backtest iteration until its entries show
   gross forward returns that clear fees (§5).

## 2. Edge claim

In a BTC up-regime, a pair that has already broken 1–4% above its prior 24h high on
expanded volume is in a confirmed advance that tends to continue over the following
one to three days by more than the 0.9–1.2% round-trip cost — because family A's
replay showed winners peak late (median ~14h, 73% of ≥4% movers after 6h), barely dip
on the way (median drawdown −0.71% before the 24h peak), and reward extension rather
than anticipation.

Honesty about the evidence: the seed observation is 135 in-sample trades from a
retired family, and the program has now falsified four short-horizon long designs on
this market (v1 chase, v2 pullback, b′ limit, A breakout), all at roughly zero gross
edge. The prior is against family B too. That is exactly what phase 0 is for: if the
gross edge is not there, this family dies before costing anything.

**How this differs from v1 (which chased and died):** v1 bought "already up 3%" with
no structural reference, unbounded extension, and short-horizon exits that sold into
the shakeout. Family B requires a structure reference (the prior 24h high), a bounded
extension band above it (past the breakout, not parabolic), volume confirmation, a
multi-day horizon — and a pre-registered gross-edge gate that v1 never had to pass.

## 3. Design (starting defaults; every number is a dev-window knob, one at a time)

Signals stay pure-pandas in `momentum_signals.py` with TDD; strategy class stays
`MemeMomentum`; timeframe stays 15m (signals computed over longer windows); harness
and arm plumbing unchanged from family A.

**Regime gate (unchanged, fail-closed):** BTC 1h close > EMA(50) and EMA(20) >
EMA(50), merged with the real +45m informative offset. No entries otherwise.

**Entry — all on the firing 15m bar:**

| # | Condition | Default | Param |
|---|---|---|---|
| 1 | Regime OK | — | — |
| 2 | Reference: rolling high over prior `ref_lookback` candles (shift(1)-lagged) | 96 candles (24h) | `ref_lookback=96` |
| 3 | Confirmed escape: close ≥ ref high × (1 + `min_extension`) | ≥1% above | `min_extension=0.01` |
| 4 | Not parabolic: close ≤ ref high × (1 + `max_extension`) | ≤4% above | `max_extension=0.04` |
| 5 | Volume: firing-candle volume ≥ `volume_mult` × rolling mean over `volume_window` | 2.0× over 96 | `volume_mult=2.0`, `volume_window=96` |

Entry pricing is market (next-candle open) with **both** family-A bounds carried
forward: the fill-rate veto in `confirm_trade_entry` enforces the upper band against
the signal-bar-frozen reference (a gap open above `max_extension` is a refused chase),
and unit tests must assert signal close AND fill rate against the frozen reference.
One new bound: a fill below the *lower* band is accepted (paying less than
pre-registered is fine; only paying more is the v1 trap).

**Exits (starting) — multi-day, sized to the fee hurdle:**

| Layer | Default |
|---|---|
| Hard stop | −3% (`stoploss=-0.03`) — family A measured tighter-is-less-bad and winners that barely dip; grid {−2%, −3%, −4%} |
| ROI ladder | `{0: 0.10, 1440: 0.05, 2880: 0.025}` (24h/48h rungs) — the target must dwarf the ~1% cost |
| Trailing | +2% trail after +5% offset |
| Stagnation | Off by default; {24h, 48h} are dev knobs. Multi-day holds park slots — median/max hold and slot occupancy diagnostics stay mandatory every run. |

**Protections, sizing, bankroll:** unchanged from family A (CooldownPeriod,
StoplossGuard, MaxDrawdown, `--enable-protections` every run; 10% of current equity
per trade, `max_open_trades: 10`, $750 cap; raises are Austin's explicit call).

**Knob discipline (pre-registered):**

- One dev iteration = one knob changed from the current best config, hypothesis
  logged in `docs/backtests.md` (DEV table) **before** the run.
- Pre-registered grids: `ref_lookback` {48, 96, 192}; `min_extension` {0.005, 0.01,
  0.02}; `max_extension` {0.03, 0.04, 0.06}; `volume_mult` {1.5, 2.0, 3.0}; stop
  {−0.02, −0.03, −0.04}; ROI shape {default, wider `{0:0.15, 2880:0.06, 5760:0.03}`,
  tighter `{0:0.06, 720:0.03, 1440:0.015}`} (ladder moves as one knob); trailing
  {default, off}; stagnation {off, 24h, 48h}. Any value outside these sets needs a
  recorded reason.
- **Hard budget: 10 dev iterations total** (down from family A's 15 — phase 0 does
  the entry screening that family A spent iterations discovering it needed). One
  iteration = both arms over the full dev window.

## 4. Two universe arms (unchanged from family A, pre-registered)

Same two arms, same construction, same fees: **L** top-30 by prior-month volume,
0.0045/side; **D** rank-slice 31–100 then $100k/day floor, 0.006/side. Round trips to
clear: 0.9% (L) / 1.2% (D). All family-A caveats stand: volume rank is the down-cap
proxy, survivor-only history flatters old months, backtest fills flatter breakout
market orders, `rank_pairs_for_month` remains the single source of truth.

## 5. Validation protocol (pre-registered)

| Phase | Window | Rules |
|---|---|---|
| **Phase 0 — gross-edge kill gate** | 2024-02 → 2025-08 (dev) | Entry-only replay of the §3 entry grid using the validated `scripts/path_analysis` engine — no exits, no backtests, no iteration spent. For every entry-grid cell (both arms): mean **gross** forward return at pre-registered horizons {24h, 48h, 96h} with bootstrap 95% intervals, plus trades per up-regime week. **Kill bar:** unless at least one cell has, on at least one arm and one horizon, mean gross return > the arm's round trip AND a bootstrap 95% lower bound > 0, family B dies here at zero iterations and the holdout stays sealed for the next family. **Selection rule, disclosed in advance:** if the bar is passed, the best qualifying cell becomes the iteration-1 baseline — one selection event, bounded by the pre-registered grid, reported in full (every cell published, not just the winner). |
| **Develop** | 2024-02 → 2025-08 | §3 knob discipline, hard budget 10 iterations, both arms every run, logged before each run. No positive config within budget → family dies, holdout stays sealed. |
| **Freeze** | — | One config, written into this spec by amendment; per-arm proceed rule as in family A. |
| **Holdout — sealed kill test #1** | 2025-09 → 2026-01 | **Inherited intact from family A — never opened.** One run per arm, frozen config, §6 bar. Any post-peek change burns it permanently. |
| **Kill test #2** | 2026-02 → 2026-07 (burned) | One run per surviving arm. Fail = dead; pass = weak corroboration only. |
| **Paper — the verdict** | Aug 2026+, ≥2 weeks | The only approval evidence. Live needs Austin's explicit "I am ready to go live." |

Multiplicity, stated before any run: program-wide this is family #3; two arms are two
shots at each kill test; verdicts are per-arm. Phase 0's grid-wide look is the one
place this family searches wide, and it is bounded, entry-only, and fully published.

## 6. Survival bar (per arm, on the holdout)

Unchanged in shape from family A: positive total profit at the arm's fee AND
bootstrap 95% lower bound on mean per-trade net > 0; frequency ≥5 trades/week
averaged over up-regime periods; report max monthly drawdown, flag any month >25%.

**Open question for Austin at the gate (decide before phase 0 runs, not after):**
a 1–4% band above a 24h high fires less often than family A's at-the-edge trigger,
and multi-day holds occupy slots longer. If B cannot make 5 trades/up-week, is that a
kill (recommended — fee-clearing families that trade rarely are hard to distinguish
from luck in a 5-month holdout) or does the bar get re-set now, in writing, with the
holdout still sealed? Phase 0 reports the frequency number per cell either way.

## 7. Traps carried forward (do not re-learn these)

All of family A §7, plus its post-mortem additions:

- Parse results from freqtrade stdout, never `.last_result.json`.
- Tick rounding in fill verification; +45m informative offset in regime audits.
- No candle downloads before August; `--dl-trades` overwrites feathers — back up first.
- Assert BOTH entry bounds (signal close and fill rate) against the frozen reference.
- Never compare net-of-fee quantities against gross price levels.
- Pin every analysis population to a committed manifest, never "latest results" —
  rerunning overwrites summaries and the wrong population can pass its own checks.
- Rankings across cells mean nothing until pairwise differences exclude zero.
- freqtrade applies today's exchange minimums at historical prices (STAKE-SKIP);
  log the skip count every run.
- Judge exits only on uncensored candle replay past entry, never closed-trade records.

## 8. Definition of done for this document

research-auditor pass → Austin reviews and approves → implementation plan → TDD build
→ phase 0 → (only if the kill bar is passed) dev phase. Until his approval: **no
strategy code, no harness changes, no runs.** This spec ends at his gate. STOP.
