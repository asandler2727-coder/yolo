# YOLO family A — range breakout + volume, two universe arms

**Date:** 2026-07-20
**Status:** DRAFT — awaiting Austin's spec-review gate. No code before his approval.
**Opens:** tabled family A per the v2 brief §3 rules (pullback family exhausted with good
process — see `2026-07-20-yolo-b-prime-limit-entry.md` §4 and
`docs/exit-path-analysis-2026-07-20.md`).
**Still governs:** master spec §6 risk guardrails and §8 security rules; v2 brief regime
filter and amended gate shape. Protections never weakened. `dry_run` stays true.
**Austin's direction (2026-07-20):** "family A, and test both — liquid coins and
down-cap coins."

---

## 1. What is new here

Two things change versus every prior attempt, and both need Austin's sign-off:

1. **New strategy family.** Range-coil breakout entries replace pullback entries.
   Three pullback-family designs (v1 chase, v2 market pullback, b′ limit pullback)
   were falsified with verified mechanics; the family was declared exhausted under a
   rule written before the last run.
2. **New validation protocol.** Feb–Jul 2026 is contaminated: we graded roughly thirty
   configurations against it and extracted detailed structure from it (shakeout depth,
   winner timing, regime splits). It can still honestly *kill* a design — its bias runs
   toward passing — but it can no longer approve one. The disk holds full Kraken history
   (BTC from 2013; 525 of 628 pairs start before 2026; verified 2026-07-20), and nothing
   in this program has ever opened the pre-2026 part. So: develop on old data, verdict on
   a sealed never-opened window, then the burned window as a kill test, then paper.

Using Feb–Jul-derived findings (peak sizes, shakeout behavior) to *motivate* this design
is fine under this protocol — that window no longer serves as approval evidence.

## 2. Edge claim

In a BTC up-regime, a pair that has coiled in a tight multi-hour range and then closes
above the range high on expanded volume tends to begin a multi-hour advance large enough
to clear 0.8–1.0% round-trip costs — because the breakout marks the *start* of the move.

Why this family, given everything that failed: the uncensored path replay showed the
moves exist (median 24h peak +4.3% from signal points; winners peaking mostly after 6h).
v1 bought moves after they finished. v2/b′ bought dips against them and either ate the
shakeout or missed the movers. A breakout entry is the remaining placement: flat before,
in as the move starts, never more than a hair above a multi-hour equilibrium price. The
v2 brief's own warning is the design's hard constraint: this must never degenerate into
"buy because price is already up 3%" (v1 in disguise).

## 3. Design (starting defaults; every number is a dev-window knob, one at a time)

Signals stay pure-pandas in `momentum_signals.py` with TDD; strategy class stays
`MemeMomentum` (configs/Docker stable); harness unchanged except arm plumbing (§4).

**Regime gate (unchanged from v2, fail-closed):** BTC 1h close > EMA(50) and
EMA(20) > EMA(50), merged with the real +45m informative offset. No entries otherwise.

**Entry — all on the firing 15m bar:**

| # | Condition | Default | Param |
|---|---|---|---|
| 1 | Regime OK | — | — |
| 2 | Range formed: rolling high/low over prior `range_lookback` candles (excluding current), width (high−low)/low ≤ `range_max_width` | 48 candles (12h), ≤6% | `range_lookback=48`, `range_max_width=0.06` |
| 3 | Breakout: close > range high | — | — |
| 4 | Anti-chase: close ≤ range high × (1 + `max_extension`) — do not buy escaped trains | ≤1.5% above | `max_extension=0.015` |
| 5 | Volume: breakout-candle volume ≥ `volume_mult` × rolling mean over `volume_window` | 2.0× over 48 | `volume_mult=2.0`, `volume_window=48` |

Entry pricing is **market** (next-candle open, freqtrade default). The b′ record stands:
resting limits below the signal select for losers and miss the movers. No retest-limit
variant in v1 of this family (knob list).

**Exits (starting):**

| Layer | Default |
|---|---|
| Hard stop | −4% (`stoploss=-0.04`); structural stop at range low capped −5% is on the knob list |
| ROI ladder | `{0: 0.05, 240: 0.03, 480: 0.015}` — wider than v2's; winners here peak late |
| Trailing | +1.2% trail after +3% offset |
| Stagnation | Exit if profit <+1% after 4h (16 candles) — a breakout that hasn't worked fast is a fakeout |

**Protections/bankroll (hard, unchanged):** CooldownPeriod, StoplossGuard, MaxDrawdown;
$750 total / 3×$250; `--enable-protections` in every run.

## 4. Two universe arms (pre-registered)

Same strategy, same single frozen config for both arms — arms differ **only** in
universe and fee. Per-arm parameter forks are a scope change needing Austin.

| Arm | Universe (prior-month avg daily quote volume) | Backtest fee |
|---|---|---|
| **L** (liquid) | Top 30, floor $250k/day — the existing harness, unchanged | 0.004/side |
| **D** (down-cap) | Rank 31–100 **and** floor $100k/day | 0.005/side (0.4% taker + 0.1% pre-registered slippage handicap) |

Depth verified back through 2024 (`scripts/universe_depth.py`, run 2026-07-20): arm L has
43–124 qualifying pairs every month; arm D's band holds 41–70 pairs above $100k/day every
month. Honest labels and caveats:

- We have no market-cap data; **volume rank is the down-cap proxy.** Arm D is really
  "mid/low-liquidity Kraken USD pairs."
- **Survivorship bias:** old months contain only pairs Kraken still lists today; anything
  delisted since is missing. This flatters 2024 more than 2025. Unfixable without
  historical listing records; disclosed for the auditor and for any verdict readout.
- Arm D backtest fills are optimistic in thin books even with the fee handicap; the
  paper phase (§5) is where real spreads get measured before any live talk.
- `rank_pairs_for_month` stays the single source of truth for membership; arm D is a
  parameterization of it (rank band + floor), not a duplicate.

## 5. Validation protocol (pre-registered)

| Phase | Window | Rules |
|---|---|---|
| **Develop** | 2024-02 → 2025-08 (18 months; ranking months 2024-01 → 2025-07) | Iterate freely, **one conceptual knob at a time**, every run logged in `docs/backtests.md` marked DEV with the knob changed and the hypothesis. Both arms run each time. If no config reaches positive dev expectancy, the family dies here and the holdout stays sealed. |
| **Freeze** | — | The chosen config is written into this spec by amendment. After that, no signal/exit/param edits. |
| **Holdout (verdict)** | 2025-09 → 2026-01 (5 months, sealed, never opened by this program; ~38% up-regime — judgeable) | **ONE run per arm** with the frozen config. Gate per arm (§6). Any post-peek change burns this holdout permanently. |
| **Kill test** | 2026-02 → 2026-07 (burned window) | One run per surviving arm. **Fail = arm dead regardless of holdout. Pass = weak corroboration only, never approval evidence.** |
| **Paper** | Aug 2026+, ≥2 weeks per master spec §9 | Only for arms passing all above, only on Austin's word. Live requires his explicit "I am ready to go live." |

Multiplicity, stated before any run: two arms = two shots at the holdout; verdicts are
per-arm (one arm passing does not validate the other). Program-wide this is family #2 —
the attempt count keeps counting.

This protocol **supersedes the blanket "no tuning" constraint inside the dev window
only**. Everywhere else (holdout, kill test, paper) single pre-registered runs remain
the law. Data note: dev and holdout windows come entirely from the bulk-export candles
already on disk (complete through 2026-03-31 from export + Apr–Jul via API); the DOGE
Apr–May 2026 hole touches only the kill window and is already recorded.

## 6. Gate (per arm, on the holdout)

| Leg | Rule |
|---|---|
| Profit | Positive total profit at the arm's fee (§4) over the 5 holdout months |
| Frequency | ≥5 trades/week averaged over up-regime periods (v2 amended-gate definition) |
| Drawdown | Report max monthly DD; flag to Austin if any month >25%; protections always on |

Fail either of the first two legs → that arm is dead. Both arms dead → family A is
exhausted, and the recorded next step is Austin's call again (family B / C / stop).
This sentence is the pre-registered meaning of a holdout fail: it is an answer, not a
cue to retune.

## 7. Traps carried forward (do not re-learn these)

- Parse result files from freqtrade stdout, never `.last_result.json` (Docker bind-mount
  stale-pointer bug, fixed and unit-tested).
- Any fill/price verification must allow for tick rounding (b′'s XCN false alarm).
- Regime audits must reconstruct the +45m informative offset (`verify_regime_gating.py`).
- No new candle downloads needed before August; if one ever runs, `--dl-trades`
  conversion **overwrites** feathers — back up first (recorded 2026-07-20 incident).
- New for this family: a unit test must assert the entry candle's close sits within
  `max_extension` of the range high — the invariant that keeps A from becoming v1.

## 8. Definition of done for this document

Austin reviews and approves this spec → implementation plan → TDD build → dev phase
begins. Until his approval: **no strategy code, no harness changes, no runs.** This
spec ends at his gate. STOP.
