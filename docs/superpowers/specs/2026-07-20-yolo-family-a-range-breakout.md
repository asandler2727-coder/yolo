# YOLO family A — range breakout + volume, two universe arms

**Date:** 2026-07-20
**Status:** DRAFT v2 — audited (research-auditor/opus 2026-07-20, verdict REVIEW) and
revised per all seven findings (§9). Awaiting Austin's spec-review gate. No code before
his approval.
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
   in this program has ever opened the pre-2026 part. So: develop on old data, survive a
   sealed old-data kill test and then the burned-window kill test, and let **paper
   trading carry the verdict** (the audit showed survivor-only history biases even the
   sealed window toward passing — §5).

Using Feb–Jul-derived findings (peak sizes, shakeout behavior) to *motivate* this design
is fine under this protocol — that window no longer serves as approval evidence.

## 2. Edge claim

In a BTC up-regime, a pair that has coiled in a tight multi-hour range and then closes
above the range high on expanded volume tends to begin a multi-hour advance large enough
to clear 0.8–1.0% round-trip costs — because the breakout marks the *start* of the move.

Why this family, given everything that failed: the uncensored path replay showed the
moves exist (median 24h peak +4.3% from signal points; winners peaking mostly after 6h).
Audit note: those numbers were measured on the *pullback*-signal population, not on
breakout entries — they prove multi-hour fee-clearing moves happen in this market and
nothing more. Family A's own move statistics get measured on the dev window.
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

Entry pricing is **market** (next-candle open, freqtrade default), with the anti-chase
cap enforced **at the fill, not only at the signal**: `confirm_trade_entry` vetoes the
entry when the fill rate exceeds range high × (1 + `max_extension`). Without the veto, a
candle can close inside the cap and gap open above it — and we would buy the gap, v1 in
disguise (the audit's top finding; worst on arm D's thin books). Vetoed gap-opens are
accepted missed fills, and this is not b′'s mistake in reverse: b′ demanded a discount
below the signal and selected for falling coins; this veto only refuses to pay *more*
than the pre-registered price. The cap's range-high reference is **frozen at the signal
bar** — it never ratchets with the rolling range while an entry is pending, because a
rolling reference would quietly re-admit the chase (auditor pin). Unit tests must assert
both bounds — signal close AND fill rate — against the frozen reference. The b′ record
stands: no resting limits below the signal, no retest-limit variant in v1 of this family.

**Exits (starting):**

| Layer | Default |
|---|---|
| Hard stop | −4% (`stoploss=-0.04`); structural stop at range low capped −5% is on the knob list |
| ROI ladder | `{0: 0.05, 240: 0.03, 480: 0.015}` — wider than v2's; winners here peak late |
| Trailing | +1.2% trail after +3% offset |
| Stagnation | Exit if profit <+1% after **8h** (32 candles). Audit note: the replay evidence says winners peak late (median ~14h; 73% of ≥4% movers after 6h) and v2's 6h cut fed its loss mechanism — the "breakouts work fast" hunch is unproven and does not get to set a tight default. 4h/12h/off are dev knobs. |

**Protections/bankroll (hard, unchanged):** CooldownPeriod, StoplossGuard, MaxDrawdown;
$750 total / 3×$250; `--enable-protections` in every run.

**Knob discipline (pre-registered; closes the audit's unbounded-search finding):**

- One dev iteration = one knob changed from the current best config, hypothesis stated
  and logged in `docs/backtests.md` (DEV table) **before** the run.
- Knob taxonomy: each named parameter is one knob; the ROI ladder moves as ONE knob (a
  shape choice, not three free numbers); the range definition counts as two knobs
  (`range_lookback`, `range_max_width`).
- Pre-registered candidate values: `range_lookback` {32, 48, 96}; `range_max_width`
  {0.04, 0.06, 0.08}; `volume_mult` {1.5, 2.0, 3.0}; `max_extension` {0.01, 0.015, 0.02};
  stagnation {4h, 8h, 12h, off} (the "off" option exists because the cited median peak
  is ~14h — beyond every timed value; auditor pin); stop {−4% fixed, structural
  range-low capped −5%}; ROI shape
  {default, wider `{0:0.07, 360:0.04, 720:0.02}`, tighter `{0:0.03, 120:0.02, 360:0.01}`};
  trailing {default, off}. Any value outside these sets needs a recorded reason.
- **Hard budget: 15 dev iterations total** (one iteration = both arms over the full dev
  window). No positive-expectancy config within 15 → family A dies in dev and the
  holdout stays sealed for the next family.
- Dev diagnostics must log, per run, the fill-veto count and the 24h path of vetoed
  entries. If the best movers gap through the cap, this family repeats b′'s
  missed-mover failure from above instead of below — measure it, don't assume
  (auditor pin).

## 4. Two universe arms (pre-registered)

Same strategy, same single frozen config for both arms — arms differ **only** in
universe and fee. Per-arm parameter forks are a scope change needing Austin.

| Arm | Universe (prior-month avg daily quote volume) | Backtest fee |
|---|---|---|
| **L** (liquid) | Top 30, floor $250k/day — the existing harness, unchanged | 0.0045/side (0.4% taker + 0.05% slippage) |
| **D** (down-cap) | Rank the full USD set by prior-month volume, slice positions 31–100, then drop members under the $100k/day floor — 41–70 pairs/month survive | 0.006/side (0.4% taker + 0.2% slippage) |

Slippage handicaps were raised from the draft (0.004/0.005) on the audit's finding: a
market order buying a breakout hits the thinnest side of the book at the worst possible
moment, so zero-slippage fills flatter exactly the trades this strategy makes. Round
trips must clear 0.9% (L) / 1.2% (D). Pre-registered before any run.

Depth verified back through 2024 (`scripts/universe_depth.py`, run 2026-07-20): arm L has
43–124 qualifying pairs every month; arm D's band holds 41–70 pairs above $100k/day every
month. Honest labels and caveats:

- We have no market-cap data; **volume rank is the down-cap proxy.** Arm D is really
  "mid/low-liquidity Kraken USD pairs."
- **Survivorship bias:** old months contain only pairs Kraken still lists today; anything
  delisted since is missing. This flatters 2024 more than 2025. Unfixable without
  historical listing records; disclosed for the auditor and for any verdict readout.
- Even with the raised handicaps, backtest fills stay optimistic for breakout market
  orders; the paper phase (§5) is where real spreads get measured before any live talk.
- `rank_pairs_for_month` stays the single source of truth for membership; arm D is a
  new **mode** of it — rank-slice positions 31–100 first, then apply the floor, the
  reverse order of arm L's floor-then-top-N. Implement as its own path with its own
  tests; never by reusing arm L's logic (auditor pin).

## 5. Validation protocol (pre-registered)

| Phase | Window | Rules |
|---|---|---|
| **Pre-dev check** | — | Bound the survivorship hole before any run: pull Kraken's 2024–2026 delisting/removal notices and count USD pairs that traded in the dev/holdout windows but are gone today (audit's next-experiment). A large share gone — likeliest in arm D's band — gets recorded and hardens the suspicion applied to any later "pass." |
| **Develop** | 2024-02 → 2025-08 (18 months; ranking months 2024-01 → 2025-07) | Iterate under §3 knob discipline, **hard budget 15 iterations**, every run logged in `docs/backtests.md` marked DEV with knob + hypothesis. Both arms run each time. No positive config within budget → family dies here and the holdout stays sealed for the next family. |
| **Freeze** | — | Freeze picks **ONE** config, written into this spec by amendment; after that, no signal/exit/param edits. Per-arm proceed rule (auditor pin): an arm goes to the holdout only if the frozen config is dev-positive **on that arm**. If no config is positive on both arms, freeze the one with the better pooled (both-arm) expectancy and only its positive arm proceeds — disclosed as a selection event; the widening this allows is bounded by the 15-run budget and the per-arm holdout bars. |
| **Holdout — sealed kill test #1** | 2025-09 → 2026-01 (5 months, ~38% up-regime — judgeable) | **ONE run per arm** with the frozen config, graded by the §6 survival bar. Fail = arm dead. Survive = permission to proceed, **not approval** — survivor-only history biases this window toward passing, the same direction as the burned window (audit finding). Any post-peek change burns it permanently. |
| **Kill test #2** | 2026-02 → 2026-07 (burned window) | One run per surviving arm. Fail = arm dead regardless of the holdout. Pass = weak corroboration only. |
| **Paper — the verdict** | Aug 2026+, ≥2 weeks per master spec §9 | The first data free of survivorship and fill optimism — **this is what approves an arm.** Only for arms surviving everything above, only on Austin's word; live needs his explicit "I am ready to go live." |

Multiplicity, stated before any run: two arms = two shots at each kill test; verdicts
are per-arm (one arm surviving does not validate the other). Program-wide this is
family #2 — the attempt count keeps counting.

Honesty notes on "sealed": before sealing, we looked at exactly two aggregate
properties of the holdout window — pair-depth counts and BTC regime mix, to confirm an
up-regime-gated strategy is judgeable there — and no price paths, signals, or
performance. Disclosed here because "never opened" would otherwise overstate it. The
clean-window supply is also finite: if family A burns this holdout, the next family's
sealed window must come from months accrued after July 2026; if A dies in dev, the
holdout stays sealed and passes intact to the next family.

This protocol **supersedes the blanket "no tuning" constraint inside the dev window
only**. Everywhere else (holdout, kill test, paper) single pre-registered runs remain
the law. Data note: dev and holdout windows come entirely from the bulk-export candles
already on disk (complete through 2026-03-31 from export + Apr–Jul via API); the DOGE
Apr–May 2026 hole touches only the kill window and is already recorded.

## 6. Survival bar (per arm, on the holdout)

| Leg | Rule |
|---|---|
| Profit | Positive total profit at the arm's fee (§4) **and** bootstrap 95% lower bound on mean per-trade net profit > 0 (existing `scripts/path_analysis` tooling). A bare positive total over ~40–100 trades is one lucky month — audit finding. Per-month profits reported as diagnostics. |
| Frequency | ≥5 trades/week averaged over up-regime periods (v2 amended-gate definition) |
| Drawdown | Report max monthly DD; flag to Austin if any month >25%; protections always on |

Fail either of the first two legs → that arm is dead. Both arms dead → family A is
exhausted, and the recorded next step is Austin's call again (family B / C / stop).
This is the pre-registered meaning of a holdout fail: an answer, not a cue to retune.
Surviving means proceeding to kill test #2 and, on Austin's word, paper — approval
lives there (§5), not here.

## 7. Traps carried forward (do not re-learn these)

- Parse result files from freqtrade stdout, never `.last_result.json` (Docker bind-mount
  stale-pointer bug, fixed and unit-tested).
- Any fill/price verification must allow for tick rounding (b′'s XCN false alarm).
- Regime audits must reconstruct the +45m informative offset (`verify_regime_gating.py`).
- No new candle downloads needed before August; if one ever runs, `--dl-trades`
  conversion **overwrites** feathers — back up first (recorded 2026-07-20 incident).
- New for this family: unit tests must assert BOTH anti-chase bounds — the signal
  candle's close within `max_extension` of the range high AND the fill-rate veto
  against the signal-bar-frozen reference (§3) — the invariant that keeps A from
  becoming v1.

## 8. Definition of done for this document

Austin reviews and approves this spec → implementation plan → TDD build → pre-dev
survivorship check → dev phase begins. Until his approval: **no strategy code, no
harness changes, no runs.** This spec ends at his gate. STOP.

## 9. Audit record

research-auditor (opus), 2026-07-20, verdict **REVIEW** on draft v1. All seven
confirmed findings addressed in this revision:

1. Anti-chase cap bounded the signal close while the market fill at next open was
   unbounded (gap-through = v1 in disguise) → cap now enforced at the fill via
   `confirm_trade_entry` veto; tests must assert both bounds (§3).
2. 4h stagnation exit contradicted the cited late-peak evidence and re-imported v2's
   loss mechanism → default 8h; tighter cuts are knobs, the "fast breakout" hunch
   demoted to a dev hypothesis (§3).
3. Bare positive-total holdout gate is one-lucky-month weak → bootstrap 95% lower
   bound on per-trade net > 0 added to the profit leg (§6).
4. Unbounded dev search behind a fuzzy "one knob" rule → knob taxonomy, pre-registered
   value grids, hard 15-iteration budget (§3).
5. The +4.3% median-peak stat was measured on the pullback population → relabeled as an
   existence proof for the market, not a breakout forecast (§2).
6. Survivor-only history biases the sealed holdout toward passing, same direction as
   the burned window → holdout demoted to sealed kill test #1, paper trading carries
   the verdict, pre-dev delisting-bounding check added (§5).
7. Zero/0.1% slippage flatters breakout market orders at their worst moment →
   handicaps raised to 0.0045 (L) / 0.006 (D) (§4).

Also pinned per audit: arm-D construction order (rank-slice, then floor — §4); the
"sealed" window's disclosed aggregate peek and the finite clean-window supply (§5).

**Confirmation pass (same auditor, 2026-07-20): GO-to-gate.** All seven findings
resolved, all pins resolved, nothing material broken. Its six carry-forward items —
freeze the cap's range-high reference at the signal bar; define the per-arm freeze/
proceed rule; add stagnation "off" to the grid; log fill-veto diagnostics in dev; sync
§7 to the both-bounds rule; build arm D as its own ranking path — were folded into
this spec text the same day (none were gate-blockers). The auditor's standing caveat
for later readouts: a holdout fail under the strict §6 bar means "no edge clearing a
strict bar on a survivor-flattered window," not proof no edge exists.
