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

Open methodology question for the final gate run: the backtest does not currently apply
the strategy's protections (freqtrade needs `--enable-protections`); live, the 15%
MaxDrawdown halt would have stopped February long before -48%. Decide before the
go/no-go verdict whether the gate run should enable them for realism.

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
