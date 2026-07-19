# Backtest log

All runs: `.venv/bin/python scripts/rolling_backtest.py 2026-02 2026-07` at `--fee 0.004`
(Kraken taker). Gate: ≥5 trades/week AND positive total profit.

## Preliminary pipeline-validation run — 2026-07-19 — NOT GATE-VALID

Run while the historical download was still in progress, on the **13 pairs downloaded so
far** (alphabet-early: mostly illiquid small caps + AAVE/ADA/DOGE). Purpose was to prove
the harness end-to-end (freqtrade 2026.4 result schema matched; no code changes needed),
not to judge the strategy. This universe is heavily biased toward exactly the illiquid
junk the live VolumePairList ($250k/day floor) would never trade, so the loss numbers
below are expected to be much worse than the real universe.

Params: defaults (momentum_threshold 0.03, volume_mult 2.0, stoploss -0.06,
roi {0: 0.10, 120: 0.04, 360: 0.02}).

| Month | Trades | Profit % | Max DD % |
|---|---|---|---|
| 2026-02 | 86 | -54.72 | 55.49 |
| 2026-03 | 90 | -61.99 | 62.47 |
| 2026-04 | 98 | -44.39 | 46.63 |
| 2026-05 | 60 | -16.23 | 26.23 |
| 2026-06 | 112 | -35.33 | 46.70 |
| 2026-07 | 43 | -13.22 | 13.95 |

Total: 489 trades, 18.76 trades/week, -225.88% summed monthly profit, gate **FAIL**
(profit leg; the trades/week leg passes with big margin).

## Real baseline, Feb–Mar 2026 full universe — 2026-07-19

Data: official Kraken bulk OHLCVT export (all pairs through 2026-03-31), 582 USD pairs on
disk; ranking + backtest windows both fully covered for Feb and Mar. Apr–Jul pending
download; when it lands it serves as out-of-sample validation for whatever Task 6 selects.
Params: defaults (as above). Run: `rolling_backtest.py 2026-02 2026-03`.

| Month | Trades | Profit % | Max DD % |
|---|---|---|---|
| 2026-02 | 89 | -48.57 | 48.57 |
| 2026-03 | 90 | -25.66 | 25.79 |

Total: 179 trades, 20.6 trades/week, -74.23%, gate **FAIL** (profit leg; frequency leg
passes 4x over).

~~Open methodology question~~ RESOLVED 2026-07-19 (independent critique, see
docs/design-critique-2026-07-19.md): the harness now passes `--enable-protections`
and `rank_pairs_for_month` enforces the live $250k/day quote-volume floor. All runs
recorded above predate those fixes, so future runs are not directly comparable —
rerun the baseline as a control before comparing numbers.

Takeaways for Task 6 tuning (to revisit on full data):
- Signal frequency is not the problem — 3.7x the 5/week floor even on 13 pairs.
- Losses concentrated in illiquid small caps; the real top-30-by-volume universe should
  behave differently. Do not tune anything against this run.
- Consider mirroring the live $250k/day volume floor in `rank_pairs_for_month` so backtest
  months can never include pairs the live pairlist would reject (harness currently takes
  top-N with no floor — only matters when few pairs have data).

## Task 6 sweep, Feb–Mar 2026 — 2026-07-19 — ALL VARIATIONS FAIL

One parameter changed per run from the defaults; all at `--fee 0.004`, months 2026-02..03.

| Param | Value | Trades/wk | Profit % | Max DD % | Gate |
|---|---|---|---|---|---|
| (baseline) | — | 20.60 | -74.23 | 48.57 | FAIL |
| momentum_threshold | 0.02 | 26.24 | -78.84 | 49.18 | FAIL |
| momentum_threshold | 0.04 | 14.84 | -70.28 | 43.29 | FAIL |
| momentum_threshold | 0.05 | 10.36 | -30.23 | 26.10 | FAIL |
| volume_mult | 1.5 | 21.17 | -69.17 | 46.84 | FAIL |
| volume_mult | 3.0 | 17.84 | -67.33 | 38.17 | FAIL |
| stoploss | -0.05 | 22.21 | -70.57 | 49.74 | FAIL |
| stoploss | -0.08 | 20.02 | -68.05 | 45.15 | FAIL |
| roi_0 | 0.06 | 20.60 | -73.59 | 49.54 | FAIL |
| roi_0 | 0.15 | 20.60 | -72.43 | 46.77 | FAIL |

Market context, same window: BTC -13.9%, ETH -14.6%; the traded top-30 universe median
-13.9% (8 of 37 pairs positive). The baseline strategy lost ~5x the market; the best
variation (threshold 0.05) still lost ~2x the market. The only monotone dial is entry
strictness — stricter → fewer trades → smaller losses — the signature of negative
per-trade expectancy (chasing 15m pumps and paying 0.8% round-trip fees), not of a
mis-tuned edge.

**Verdict per spec §9 / plan Task 6 step 3: nothing passes on available data → stop and
report to Austin. No deployment, gate unchanged.** Combination grid-search on only 2
months was deliberately not attempted (overfitting risk with Apr–Jul reserved as
out-of-sample). Decision on next direction is Austin's; leading options: (a) rerun
baseline+sweep when Apr–Jul lands (regime may differ; note Feb–Mar was a bear window and
long-only momentum amplified it), (b) revise the strategy design (regime filter,
non-chasing entries, fee-aware exits) via a spec update before any further tuning,
(c) independent design critique before more spend.

## v2 pullback-in-uptrend, Feb–Mar 2026 in-sample — 2026-07-19 — GATE FAIL (profit)

First run of the **v2 redesign** (BTC 1h up-regime filter + 15m pullback-into-support
entry, non-chase, fee-aware 3/2/1% ROI ladder + −4% stop + trailing lock + 6h stagnation).
v1 (chase a completed pump) is frozen. Run: `rolling_backtest.py 2026-02 2026-03` at
`--fee 0.004 --enable-protections`, top-30-by-prior-month-volume universe.

| Month | Trades | Profit % | Max DD % | Result file |
|---|---|---|---|---|
| 2026-02 | 14 | -5.08 | 5.40 | backtest-result-2026-07-19_07-59-26.zip |
| 2026-03 | 22 | -3.28 | 5.37 | backtest-result-2026-07-19_07-59-33.zip |

Total: 36 trades, 4.14 trades/week overall, **-8.36% summed monthly profit**, worst
monthly drawdown **5.40%**, gate **FAIL** on the profit leg.

**Harness reporting bug found & fixed first (do not compare against any earlier v2
number).** `run_month` had read freqtrade's shared `.last_result.json` pointer immediately
after the container exit; over the macOS Docker Desktop bind mount that host read returned
a *stale* pointer from a prior session's v1 run, so an interim summary mis-reported v2 as
−72% (89/90 v1 trades). Fixed by parsing the result filename from freqtrade's own captured
stdout (`dumping json to "...meta.json"`), which has no filesystem race; the harness now
logs, per month, the exact file it read + trades + profit. The re-run above reproduced the
true zips exactly, confirming the fix (`scripts/test_rolling_ranking.py` covers the parser).

**Regime gating independently audited (`scripts/verify_regime_gating.py`).** Window was
37% up-regime / 63% down. All 36 entries fell inside the up-regime — none leaked into the
bear — reconstructing the BTC 1h regime with freqtrade's real +45m informative offset. So
the loss is **genuine in-regime negative expectancy, not a gating leak**. In up-regime
periods (~3.1 of 8.4 weeks) that is **11.5 trades/wk**, so the amended gate's
regime-conditional *frequency* leg passes; the failure is entirely on *profit*.

Per-trade shape: **58% win rate (21/36) but −0.69% average trade.** Winners are capped by
the ROI ladder while losers run to the −4% stop; ~0.8% round-trip taker fees erase the thin
edge. Majority-win, negative-expectancy — exactly what the profit gate exists to catch.

**vs v1, same window:** v1 lost ~−74% over 179 trades with ~48% drawdown; v2 loses −8.36%
over 36 trades with 5.4% drawdown. The redesign killed the catastrophe — it correctly sits
out the 63% bear and keeps drawdown to a third of the $750/3×$250 budget's tolerance — but
it has **not** produced positive expectancy in-sample.

**Verdict (plan Task 4 / amended gate): FAIL in-sample profit; edge not confirmed even
in-regime; OOS (Apr–Jul) pending download.** This is not "obviously broken" (36 real,
correctly-gated entries), so per the spec it is **not** a cue to auto-tune. Next direction
is Austin's call: (a) wait for the Apr–Jul OOS run before any judgment, (b) one conceptual
design change (e.g. exit asymmetry — the −4:+3 R:R with fees is the visible culprit) via a
spec update, or (c) table v2 and open the next tabled family. No deployment; gate unchanged;
protections intact.
