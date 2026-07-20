# Family A post-mortem — range-coil breakout, two universe arms

**Date retired:** 2026-07-20, on Austin's word, after the independent review
(Fable 5) confirmed the retire recommendation. Full evidence trail:
`docs/backtests.md` (DEV table, path diagnostic, structural-stop correction,
independent review section) and `docs/diagnostics/2026-07-20-family-a-*.txt`.
Spec: `docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md`.

## What it was

Long-only breakout entries on Kraken USD spot pairs, 15m timeframe, in a BTC
up-regime only. The premise: a pair that coils in a tight multi-hour range and
then closes above the range high on expanded volume is at the *start* of a
move big enough to clear fees. Two universe arms shared one config: arm L
(top-30 by prior-month volume, 0.9% round-trip cost) and arm D (volume ranks
31–100 with a $100k/day floor, 1.2%). Pre-registered protocol: dev window
2024-02 → 2025-08, hard budget 15 one-knob iterations with hypotheses logged
before each run, sealed holdout 2025-09 → 2026-01 earned only by a dev pass.

## The result

Three iterations were spent — baseline, then `range_lookback` 32 and 96 (the
strongest pre-registered case). Every cell failed the gate decisively:

| Cell | Arm L /trade | Arm D /trade |
|---|---|---|
| lookback 32 | −0.61% | −1.33% |
| lookback 48 (baseline) | −0.90% | −1.28% |
| lookback 96 | −0.84% | −1.16% |

All six bootstrap 95% intervals on mean per-trade net exclude zero, under both
iid and month-clustered resampling (e.g. baseline L: −0.90%, clustered
[−1.28%, −0.58%]). Between 15 and 18 of the 19 dev months are negative in
every cell. Trade frequency passed everywhere (17–23 trades per up-regime
week); profit failed everywhere. This is a real negative result, not noise.

## Why it failed: the entries had no gross edge

The decisive number is the fee decomposition. Arm L lost 0.90% per trade net
while paying 0.90% round trip; arm D lost 1.28% while paying 1.20%. Gross of
fees, expectancy was **approximately zero on both arms**. Fees did not erode a
small edge — there was no edge. The coil-breakout signal carried no
information about forward returns on this market at this horizon.

The moves themselves exist: the uncensored replay measured a median 24h peak
of +2.7% after entry (p75 +5.9%; 46% of entries peaked at +3% or better), and
a perfect-exit ceiling of +3.39% per trade. The entries simply captured none
of it on average, and no exit rule can manufacture expectancy that entries do
not supply.

## What was ruled out, and how

Every escape route was measured, not argued:

- **Exits are spent.** A validated forward replay (mean error 0.083% per
  trade against 1,563 recorded exits) swept the full pre-registered exit
  grid, the spec's structural stop, and a continuous stop-depth sweep from
  −1.5% to −8%. Best cell anywhere: −0.79% per trade in-grid, −0.66%
  off-grid. The −4% stop we ran sat near the worst depth — the fingerprint of
  entries with nothing to protect.
- **Every entry tightening made it worse** (width ≤0.04 → −0.98%; volume
  ≥3.0× → −0.98%; extension ≤1.0% → −1.01%; all three → −1.16%; baseline
  −0.94%). Tighter coils also produced *smaller* subsequent moves (mean 24h
  peak +4.31% → +3.73%). The coil-quality premise is inverted on this market.
- **The three untested loosening cells cannot pass either.** Loosening keeps
  the losing core, so on arm L newly admitted trades would need +9% each at a
  plausible +10% admission rate just to reach zero. The measured expectancy
  bands nearest each loosened boundary read −0.82% (width), −0.91% (volume),
  −0.25% (extension). Running iterations 4–6 on them would have been theater.
- **`range_lookback` moves trade count, not edge.** All six pairwise cell
  differences have intervals straddling zero.
- **Not a leak.** Range indicators are shift(1)-lagged; the anti-chase cap
  held on all 4,523 fills across three iterations; all 1,563 baseline entries
  opened in-regime; the holdout seal held (latest candle touched:
  2025-08-31 23:45). Survivorship bias flatters these results, which only
  strengthens the negative verdict.

## Corrections made to the record

Five claims were wrong and were corrected in place rather than quietly edited:

1. "The pre-registered space is exhausted" — false; three loosening cells
   were never tested. (The review then closed them by measurement — above.)
2. "An advisor review caught the structural-stop hole" — no such review ran;
   the hole was caught by re-reading the spec.
3. The structural-stop depth statistics had a unit error (net-of-fees depth
   compared to gross levels). True figures: median depth −3.79%, *tighter*
   than −4% on 55% of trades, cap binds on 22%. The sweep outcomes stand.
4. "Arm L's best lookback is arm D's worst, so the knob is noise" — the
   ranking ordered statistically indistinguishable numbers. The conclusion
   survives on direct evidence; the ranking argument does not.
5. The ledger claimed a stale re-run of the replay would fail loudly; it
   actually passed silently on the wrong trade population. Fixed by pinning
   selection to the committed baseline snapshot's zip manifest.

## Lessons (program-level, not family-specific)

1. **Check gross expectancy first.** One diagnostic — entry-only forward
   returns minus fees — would have killed family A before a single iteration.
   Family B's spec makes this a mandatory pre-iteration kill gate.
2. Tightening a "quality" filter and watching expectancy *fall* is a cheap,
   strong test that the filter measures nothing.
3. Rankings across cells mean nothing until the pairwise differences exclude
   zero — compute the interval before reading a pattern.
4. When a sweep claims to cover a pre-registered grid, check each cell
   against the spec's own wording (a flat −5% silently replaced the
   *structural* stop and the sweep still looked complete).
5. Never compare net-of-fee quantities against gross price levels — the unit
   error shifted every depth figure by roughly one fee round trip.
6. "Latest results per month" selection breaks silently the moment a later
   run overwrites the summaries; pin analysis populations to a committed
   manifest.
7. freqtrade applies today's exchange minimum order sizes at historical
   prices, silently shrinking the historical universe (conservative here, but
   it must be logged).
8. Uncensored path replay of raw candles past entry — never closed-trade
   records — is the only honest basis for judging exit redesigns.

## What carries forward to family B

- **The fee hurdle is the design constraint.** Any new entry signal must
  carry enough gross edge to clear 0.9–1.2% round trip with margin. The
  program has now falsified four short-horizon long entry designs (v1 chase,
  v2 pullback, b′ limit, A breakout) on this market — all at roughly zero
  gross edge.
- **One hypothesis-grade observation:** within family A's population, the
  entries *most* extended above the range (1.0–1.5%, the band the anti-chase
  cap nearly refused) lost least — −0.25% net, which is positive gross of
  fees — and the gradient was monotone. Entries closest to the range lost
  most. Winners also barely dipped (median drawdown −0.71% before the 24h
  peak) while losers paid the full stop. Together these point at confirmed
  motion, not anticipated breakouts. This is 135 trades of in-sample
  evidence: a reason to write a hypothesis, not a result.
- **The holdout 2025-09 → 2026-01 was never opened** and passes intact to
  family B. Budget spent: 3 of 15 iterations. Baseline artifacts are
  snapshotted in `user_data/backtest_baseline_iter1/` (committed); the replay
  tooling in `scripts/path_analysis/` is validated and reusable.
