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

## v2 pullback-in-uptrend, Apr–Jul 2026 OUT-OF-SAMPLE — 2026-07-20 — GATE FAIL (profit)

First run on the reserved out-of-sample window (Apr 1 – Jul 15; data ends 2026-07-14/15,
so 2026-07 is a half month). Identical v2 params to the in-sample run — nothing tuned in
between. Run: `rolling_backtest.py 2026-04 2026-07` at `--fee 0.004 --enable-protections`,
top-30-by-prior-month-volume universe. Plan: `docs/superpowers/plans/2026-07-20-yolo-v2-oos-validation.md`.

| Month | Trades | Profit % | Max DD % | Result file |
|---|---|---|---|---|
| 2026-04 | 17 | -9.03 | 9.34 | backtest-result-2026-07-20_05-26-27.zip |
| 2026-05 | 44 | -3.55 | 6.21 | backtest-result-2026-07-20_05-26-35.zip |
| 2026-06 | 11 | -6.91 | 6.91 | backtest-result-2026-07-20_05-26-41.zip |
| 2026-07 (half) | 11 | -4.25 | 5.21 | backtest-result-2026-07-20_05-26-48.zip |

Total: 83 trades over 14.9 real weeks, **−23.76% summed monthly profit**, worst monthly
drawdown **9.34%**, gate **FAIL** on the profit leg. Every month negative.

**Data provenance (two repairs, both verified before the run):**
1. freqtrade's end-of-download trades→OHLCV conversion *overwrites* each 15m feather with
   trades-derived candles only (confirmed in the 2026.4 source: `ohlcv_store(data=ohlcv)`,
   no merge); gap-pair trades start 2026-04-01, so Jan–Mar candles would have been wiped —
   and were (post-conversion BTC feather spanned Apr 1 → Jul 15 only). Repaired from the
   pre-conversion backup via `scripts/merge_15m_backup.py` (574 pairs regained history;
   probes 0 duplicate dates; BTC seam Mar 30–Apr 2 = 384/384 candles; Apr 1–Jul 15 =
   10,080/10,080; all four ranking months returned a full 30 pairs, majors on top).
2. DOGE/USD has an unfixable Apr–May hole: Kraken's API serves this pair's trades only
   from 2026-06-01 (`--erase` cannot recover earlier). Ranking excludes DOGE correctly for
   May and June, re-includes it for July; in April it ranked #6 on March volume but had no
   April candles, so April effectively traded 29 pairs (one burned slot). Recorded, not
   repaired — no API source exists.

**Regime audit clean (`verify_regime_gating.py` on all 4 zips).** Window 44.4% up-regime /
55.6% down (BTC −4.4% over the window); **all 83 entries opened in the up-regime** — no
leak. In-regime frequency **12.6 trades/wk** (6.6 up-weeks) → the amended frequency leg
passes. (Overall: 4.78/wk by the harness's four-full-month divisor, ~5.6/wk over the real
14.9 weeks — the harness number understates because July is a half month.)

**Per-trade shape replicates in-sample: 53% win rate (44/83), −0.86% avg trade**
(in-sample: 58%, −0.69%). Same mechanism — winners capped by the 3/2/1% ROI ladder, losers
run to the −4% stop, ~0.8% round-trip taker fees — now confirmed on unseen data, in a
window with *more* up-regime exposure than in-sample (44% vs 37%).

**Combined verdict (in-sample + OOS): v2 as specified has replicated negative expectancy
in up-regimes.** Feb–Jul: 119 trades, −32.1% summed monthly profit, max monthly DD 9.34%,
both windows 100% in-regime entries. The risk redesign did hold — v1 lost −74% in 2 months
with ~48% DD; v2 loses −32% across 5.5 months with DD ≤9.3% — but the edge is negative and
consistent. **Apr–Jul is now burned as OOS:** any redesign informed by these numbers must
treat Feb–Jul as in-sample and validate on fresh (Aug+) data. Per spec: no tuning, no
deploy, protections intact. Direction is Austin's call — (a) judge v2 on the combined
record, (b) one conceptual design change via spec update (exit asymmetry is the replicated
culprit: capped +3% winners cannot pay for −4% losers plus 0.8% fees at a ~55% win rate),
or (c) table v2 and open the next tabled family.

**Follow-up (2026-07-20, after Austin chose (b)):** the exit-asymmetry premise was
tested against the recorded trade paths before implementation and **refuted** — no
mechanical exit family (trails, ladders, scale-outs, flat ROI) clears zero on these
entries; the loss lives in entry timing vs the post-entry shakeout, not in the exit cap.
Full analysis + independent research-auditor review (verdict: refutation endorsed):
`docs/exit-path-analysis-2026-07-20.md`. The (b) spec update was withdrawn; the
data-supported alternative (b′ = limit-entry deeper in the pullback, ~+2pp in-sample
upper bound) awaits Austin's direction.

---

## b′ limit-entry, Feb–Jul 2026 IN-SAMPLE — 2026-07-20 — GATE FAIL (profit)

**Design under test:** the approved b′ spec
(`docs/superpowers/specs/2026-07-20-yolo-b-prime-limit-entry.md`): v2 unchanged except
the entry rests as a limit at signal-time price × 0.98 with a 240-minute unfilled
timeout. Single pre-registered configuration, no sweeps; one full run (plus one May
smoke run of the same configuration to validate mechanics, disclosed). Harness as
always: prior-month top-30 ranking, $250k/day floor, `--fee 0.004`,
`--enable-protections`, result zips taken from freqtrade's own stdout.

| Month | Trades | Profit % | Max DD % | Result zip (2026-07-20) |
|---|---|---|---|---|
| 2026-02 | 12 | −3.27 | 4.86 | `backtest-result-2026-07-20_06-40-39.zip` |
| 2026-03 | 14 | −0.04 | 4.20 | `_06-40-46.zip` |
| 2026-04 | 23 | −2.16 | 3.42 | `_06-40-53.zip` |
| 2026-05 | 24 | −4.12 | 5.76 | `_06-41-01.zip` |
| 2026-06 | 12 | −3.50 | 5.09 | `_06-41-08.zip` |
| 2026-07 (to 15th) | 5 | −4.84 | 5.50 | `_06-41-15.zip` |

**Totals: 90 trades, −17.92%, every month negative, worst monthly DD 5.76%.**
Frequency: 3.45/wk overall (harness divisor); ~9.3/wk averaged over the ~9.7
up-regime weeks → the amended frequency leg passes. **The profit leg fails.**

**Mechanics verified (this is a real test of the design, not a broken run):**
- `scripts/verify_fill_depth.py`: 89/90 fills are exact 2%-limit fills (median
  discount 2.00%, max 2.02% = tick rounding). The 1 flagged fill (XCN/USD at
  $0.00571) was checked by hand: the fill candle's unrounded limit is
  0.98 × 0.00583 = 0.005713, which rounds on the pair's 1e-5 tick grid to exactly
  the fill price — a genuine 2% limit fill 0.34 ticks from the unrounded value,
  just past the verifier's 0.29-tick tolerance at this price scale. **All 90 fills
  verified; no clamping.**
- No `custom_price_max_distance_ratio` clamp: knob confirmed at 0.05 in the tmp
  config, and the exact-2% discounts prove the limit survived unclamped.
- `scripts/verify_regime_gating.py`: **all 90 entries opened in the up-regime.**
- `scripts/count_signals.py`: 393 signal candles Feb–Jul (61/87/74/83/69/19 by
  month) → 90 fills = **22.9% fill rate**.

**Per-trade shape:** 53.3% win rate, avg win +1.48%, avg loss −2.97%, avg trade
−0.60%, median hold 3.8h. Exits: 42 roi (+1.6% mean), 30 stagnation (−1.7%),
15 stop (−4.8%), 3 trailing (+1.1%).

**Why the audited +2pp upper bound collapsed to +0.21pp (vs v2's −0.81%/trade):**
exactly the two erosion forces the spec §3 pre-registered. Missed fills: 77% of
signals — including the straight-up movers that carried the oracle ceiling — never
dipped 2% and never filled. Adverse selection: the fills are the signals that *did*
keep falling. The 2%-cheaper entry did real work on the loss side (stops fell from
24% to 17% of trades, avg loss −2.97 vs −3.60, DD roughly halved) but couldn't
manufacture upside the filled subset didn't have.

**Pre-registered verdict (spec §4):** failing the profit leg in-sample means **the
pullback-in-uptrend family is exhausted** — entries at market lose to the shakeout,
no mechanical exit fixes it (exit-path analysis), and entries below the shakeout
lose the movers. Per the v2 brief §3 rules the next step, if any, is **one** tabled
family via a short redesign note — Austin's call. No tuning, no deploy; protections
never weakened. Feb–Jul remains burned as in-sample for this family.

---

## Family A pre-dev survivorship check — 2026-07-20

Spec §5 requires bounding the survivor hole before any dev run: today's feathers
contain only pairs Kraken still lists, so anything delisted since 2024 is missing
from every backtest universe. Method: Kraken support "Delistings" section + web
search for dated notices, then a disk check of each named asset against the 628
`*_USD-15m.feather` files.

**Dated notices found (assets; trading-disable date):**

| Notice | Assets | Disabled |
|---|---|---|
| WAVES delisting | WAVES | 2024-07-08 |
| MATIC→POL migration | MATIC (renamed, POL on disk) | 2024-09 |
| Scheduled delistings Nov 2025 | MC, INTR, CSM, ROOK, OXY, AGLD, GAL, KINT, PSTAKE, KAR | 2025-11-06 |
| Scheduled delistings Dec 2025 | UST, LUNA2, NODL, PDA, ETHW, TVK, TUSD, MOVE, BRICK | 2025-12-12 |
| Scheduled delistings Apr 2026 | PLANCK, AIR, MICHI, FLY, ANLOG, TERM, STRD | 2026-04 |
| Scheduled delistings May 2026 | AURA, BIT, BOND, BSX, FARM, GARI, K, KET, KINTO, LOBO, MOON, MV, NYM, RAIIN, RHEA, SAROS, SDN, SPC, SPICE, TEA, TEER | 2026-05 |
| Scheduled delistings Jun 2026 | TITCOIN, MXC, TOKE, ASRR, ART, UNITE, TANSSI, MIRROR, SOGNI, ALMANAK, VERSE, XRT, RETARDIO, RAVE | 2026-06 |
| Regional only (excluded from count) | XMR/DASH/ZEC (India, Canada, EEA), PORTAL (US/CA), UTU/ESX (EEA), H, KILT, RAIN, SNAPX, Kinto | various |

**Disk verification:** all 33 spot-checked delisted assets (the full Nov+Dec 2025
lists plus 13 sampled from 2026 notices, plus WAVES and MATIC) are ABSENT from
the feather set. POL (MATIC's rename) is present. So the dataset is confirmed
survivor-only, and even assets delisted AFTER the 2026-03-31 bulk-export cutoff
are gone — the export/download pipeline only ever saw currently-listed pairs.

**Bound:** at least **61 assets** were removed by the five scheduled notices
2025-11→2026-06 alone (+WAVES inside the dev window). Kraken's stated reason —
"no longer meet our internal performance standards," i.e. low volume — puts
these exactly in arm D's rank-31..100/$100k band population (41–70 pairs/month).
Their entire histories, including the decaying months INSIDE dev (2024-02→
2025-08) and holdout (2025-09→2026-01), are invisible; a decaying coin's failed
breakouts are precisely what this strategy would have bought. Assets like AGLD,
GAL, ETHW, LUNA2, MOVE very likely cleared the floors during dev months
(judgment — no volume data survives to verify).

**Caveats:** no public scheduled-delisting notices surfaced for 2024→2025-10
beyond WAVES (either Kraken began systematic monthly culls in 2025-11, or older
notices were purged from support) — so 61+ is a **lower bound**. Whether every
listed asset had a Kraken USD pair is unverifiable today, but Kraken lists USD
for nearly all spot assets. The Apr–Jun 2026 removals also thin the kill window
(2026-02→07) on top of the known DOGE hole.

**Consequence (pre-registered stance):** the survivor bias flatters dev and
holdout results, hardest on arm D. Per spec §5 this hardens skepticism on any
later "pass" — a dev-positive or holdout-surviving arm is *permitted to
proceed*, never validated, and paper trading (survivorship-free) remains the
only verdict.

---

## Family A DEV phase — spec 2026-07-20-yolo-family-a-range-breakout.md §5

Window 2024-02→2025-08 (18 months; ranking months 2024-01→2025-07). Hard budget
15 iterations; one knob per iteration, hypothesis logged BEFORE each run. Fees:
arm L 0.0045, arm D 0.006. Holdout 2025-09→2026-01 SEALED. Stagnation exit off
(Austin's gate amendment); hold/slot diagnostics mandatory. Survivorship note
above applies to every row. Stake sizing note: freqtrade applies TODAY's Kraken
minimum order sizes at historical prices, so some entries are skipped
(STAKE-SKIP) that live trading would take — conservative direction, logged per
run.

| Iter | Date | Knob (vs best) | Hypothesis (pre-run) | Arm | Trades | Profit % | Worst mo DD % | Tr/up-wk | Vetoes | Skips | Med hold h | Slots max / %full | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-20 | — (spec defaults) | Baseline: breakout-at-start placement clears fees in up-regime where pullback entries could not | L | 843 | −76.40 | 9.19 | 21.7 | 10 | 99 | 12.2 | 10 / 3.5% | FAIL — 17/19 months negative |
| 1 | 2026-07-20 | — (spec defaults) | same | D | 720 | −91.80 | 10.37 | 18.5 | 11 | 229 | 12.6 | 10 / 4.8% | FAIL — 18/19 months negative |

**Iteration 1 (baseline) readout.** Profit % is the sum of monthly percents
(harness convention). Result zips `2026-07-20_08-25-17`…`08-27-17` (L) and
`08-27-34`…`08-29-53` (D); summaries `rolling_summary_L.json` / `_D.json`.
Mechanics verified before reading anything into the numbers:
`verify_breakout_cap.py` 1563/1563 fills obey both frozen-cap bounds (max
fill/cap 0.9998); `verify_regime_gating.py` 1563/1563 entries in up-regime.
The losses are genuine in-regime negative expectancy, not a leak.

- **Loss shape (both arms):** the familiar capped-winner/full-loser asymmetry.
  L: 58% win, avg win +1.97%, avg loss −4.82%, avg trade −0.90%; exits roi 411
  / stop 351 / trailing 76 / force 5. D: 55% win, +1.94% / −5.16%, −1.28%/trade;
  roi 340 / stop 325 / trailing 53. 42–45% of trades die at the −4% stop; wins
  mostly exit at the late small ROI rungs (median hold ~12h).
- **Only positive month for BOTH arms: 2024-11** (L +0.95, D +4.20) — the smoke
  month; it is an outlier, not representative.
- **Anti-chase veto works as designed:** 21 vetoes across both arms
  (`veto_paths.py`): median 24h close of vetoed fills −2.94% (median MAE
  −5.40%) — the cap refused bad chases; no missed-mover failure from above.
- **Slots/holds (stagnation-off cost):** mean concurrency 1.1–1.3 of 10 slots,
  at-capacity only 3.5–4.8% of the span; max holds 222h (L) / 592h (D). Slot
  starvation is not the problem at baseline.
- **STAKE-SKIP 99 (L) / 229 (D):** today's Kraken minimum order sizes applied
  at 2024–25 prices skip ~10–24% of would-be entries — conservative artifact,
  noted above the table.

## Family A path diagnostic — 2026-07-20 — NO ITERATION SPENT

Between iteration 1 and any iteration 2, the question was which knob to spend
the budget on. Iteration 1 lost −0.90%/trade with a 58% win rate: capped
winners (+1.97%) against full losers (−4.82%). Two causes fit that shape and
they point at opposite knobs — worthless **entries**, or **exits** that cap
live moves. Trade records cannot separate them, because `max_rate` is censored
at exit time (the lesson that invalidated the first v2 exit analysis,
`docs/exit-path-analysis-2026-07-20.md` §1).

So both were measured against raw candles instead of guessed at:
`scripts/path_analysis/replay_family_a.py` and `entry_quality.py`; full output
in `docs/diagnostics/2026-07-20-family-a-*.txt`. **No knob was changed and no
config was graded — the 15-iteration budget still stands at 1 used, 14 left.**

**Trustworthiness first.** Trade selection is structural, not by filename: dev
window by timerange, arm by config whitelist size (L = top 30, D = ranks
31–100), latest run per month, then the per-month counts must match
`rolling_summary_{L,D}.json` exactly — 1563 trades, 843/720, 38 zips, exact
match. The replay engine reconstructs the config as run and reproduces the
recorded per-trade profit to **mean |error| 0.083%/trade** (p95 0.35%, 1492
comparable trades) against a 0.10% gate; it exits 1 below that, so the
counterfactuals are only ever read after the engine has earned it. Pinning
freqtrade's within-candle order took the crosstab against 1563 recorded exits:
the trailing stop ratchets off the candle high *before* the low is tested, and
ROI beats a ratcheted trailing stop but loses to a hard stop.

**Holdout seal held, and the guard earned its place.** Windows are truncated at
2025-09-01 and an assertion fails the run if any candle at or after it is read.
It fired on the first pass: `.loc[a:b]` is inclusive, so 65 windows were
pulling in the 00:00 candle on seal day — the first holdout bar. Fixed; the
run is now clean, with 65 trades (4.2%) flagged as seal-truncated and excluded
from the comparisons rather than silently averaged in.

**What the entries actually offered (uncensored, 1498 untruncated trades).**
Gross peak within 24h: p50 **+2.7%**, p75 +5.9%, p90 +9.7%; 46% peak ≥+3%.
Within 48h: p50 +3.9%, 58% ≥+3%. Median time-to-peak 10.1h (17.0h among the
545 that peaked ≥+4%), median dip before the peak only −0.71%, and just 9% of
those movers hit the −4% stop before paying. The moves are real: the
perfect-exit ceiling is **+3.39%/trade** (arm L, 24h). That ceiling is not
evidence of an edge — only a negative one would have been decisive — it just
rules out "there was never anything to catch."

**The exit lever is spent.** All 24 pre-registered exit variants (ROI
{default, wider, tighter} × trailing {on, off} × stop {−4%, −5%}) lose money on
both arms. Best is `roi=wider trail=off stop=−4%` at −0.83%/trade on L (−1.07%
on D) against the −0.97% as-run. Adding Austin's stagnation cut {4, 8, 12h}
gives the single best cell anywhere in the grid — `roi=wider stagnation=4h`,
**−0.75%/trade on L** — and the arms disagree on which cut wins (4h for L, 12h
for D), so even that would need a per-arm fork, a scope change. **The whole
grid spans ~0.4pp against a ~0.85pp gap to breakeven.** Tellingly, the
stagnation cuts reshape the trade completely — win rate falls 57%→28%, average
loss shrinks −4.86%→−1.84% — and the net barely moves. The loss is diffuse, not
parked in one fixable place.

**The entry lever is worse than spent — it runs backwards.** Tightening a
filter keeps a subset of trades already taken, so each pre-registered
tightening was measured directly off the recorded population. Every one makes
it worse: `range_max_width ≤0.04` −0.98%/trade (vs −0.94% pooled baseline),
`volume_mult ≥3.0` −0.98%, `max_extension ≤0.010` −1.01%, all three at once
−1.16%. The premise fails on its own terms: tighter coils produced **smaller**
subsequent moves (mean 24h peak +4.31% → +3.73%), and the volume filter was
barely binding to begin with (median signal already 3.9× its 48-bar mean;
median breakout only 0.3% above the range high, against a 1.5% cap). A quality
filter that degrades quality as you tighten it is not measuring quality.

**Verdict.** Every lever the spec pre-registered and this data can test is
negative, and the best cell in the entire space is −0.75%/trade on the better
arm. One pre-registered knob remains genuinely untestable this way —
`range_lookback` {32, 96}, which redefines the range rather than filtering it,
so it needs real runs. Loosening (width 0.08, volume 1.5×, extension 2%) is
also untestable off this data; the gradient formally points that way, but the
end of that road is "buy any breakout in an up-regime," the v1 chase the spec
forbids by name.

Recorded honestly for the freeze decision: any exit or entry shape chosen off
these tables is **more fitted than a blind grid pick**, and would owe the
sealed holdout a correspondingly higher bar. Limits that apply to every number
above: slot contention is ignored (occupancy was 1.1–1.3 of 10, so small, not
zero), month-boundary force-exits are dropped (7 trades), and all of it is
in-sample on the dev window.

### Correction and completion — structural stop — 2026-07-20 — NO ITERATION SPENT

**The exit sweep above had a hole, and the claim "all 24 pre-registered
variants" was wrong.** Spec §3's stop knob is `{−4% fixed, structural = signal
-bar range low capped at −5%}`. The sweep substituted a **flat −5%** for the
structural leg. That is not a near-miss, it is close to the opposite: flat −5%
is looser than baseline on every trade, while a structural stop was supposed to
be tighter on most. The one exit lever with a mechanism behind it — winners
barely dip (median −0.71% before the 24h peak, only 9% of movers touch −4%
first) while losers pay the full stop (−4.86%) — had never actually been run.
`scripts/path_analysis/structural_stop.py` closes that hole. Same validated
engine, same mechanic, only the per-trade stop *level* changes, so it sits
inside the 0.083%/trade envelope.

**The structural stop is not what it was assumed to be.** Measured over all
1563 entries, its depth from entry is p25 −5.80% / **p50 −4.78%** / p75 −3.74%.
It is *looser* than the −4% baseline on **69%** of trades, and the −5% cap
binds on 46%. Real coils are wider than the mechanism assumed and round-trip
fees add ~1%. It helps, and by almost nothing: best cell arm L `roi=wider
trail=off structural` **−0.79%/trade** (vs −0.83% for the same shape at −4%),
arm D −1.05% (vs −1.07%). It does exactly what it was built to do — average
loss −4.86% → −4.38% — and the win rate falls 52% → 50%, so the net barely
moves. The same diffuse-loss signature as the stagnation cut.

**Stop-depth sweep — diagnostic, outside the pre-registered grid.** Because the
structural stop turned out loose, it never tested the tight-stop idea. This
does, in full generality (roi=wider, trailing off, per-trade net):

| stop | −1.5% | −2% | −2.5% | −3% | −4% | −5% | −6% | −8% | none |
|---|---|---|---|---|---|---|---|---|---|
| arm L | −0.68% | −0.66% | −0.66% | −0.72% | −0.83% | −0.99% | −0.98% | −1.06% | −0.60% |
| arm D | −0.88% | −0.96% | −0.99% | −0.98% | −1.07% | −1.00% | −1.06% | −1.21% | −0.35% |

Negative at every depth, and the best *stopped* cell anywhere — in-spec or out
— is −0.66% (L) / −0.88% (D). Across a 5× range of stop depth the whole span is
~0.4pp on either arm.

The shape matters more than the level. **Tighter is less bad on both arms**
(L best at −2%, D at −1.5%), and the −4% we actually run sits in the worse
half, close to the pessimal depth. That is the fingerprint of entries with no
edge to protect: there is nothing worth giving room to, so you lose least by
minimising exposure. It converges with "entry tightening runs backwards" from
the opposite direction — two independent reads landing on the same conclusion,
that there is no exploitable edge here to harvest.

The no-stop column (−0.60% / −0.35%, winning 87–89%) is **not** a viable cell:
it holds up to 720h waiting on a +2% rung and is horizon- and seal-sensitive.
Read it only as confirmation that the damage sits in a tail no stop placement
can dodge.

**This is what earns the verdict.** "The exit lever is spent" is now measured
rather than assumed: ROI shape × trailing × stop depth swept continuously, and
nothing approaches breakeven. The best cell in the corrected space is
−0.79%/trade against a ~0.8pp gap. Adopting any depth off that curve would be
both a scope change (spec §3 pre-registers only two stop values) and a fit to
the dev window.

**One caveat retracted from the earlier section.** The stagnation cells sit
*outside* the validated envelope — the config as run had stagnation off, and
`custom_exit` is modelled on the candle close where freqtrade may evaluate it on
the open. Those cells are deeply negative, so plausible modelling error does not
flip them, but they should not have been reported under the blanket
"engine validated" claim. The structural-stop and depth rows above do not have
this problem.

**Forward note for family B, not a family A finding.** Round-trip fees are
**0.9%** (arm L) and **1.2%** (arm D) against a median uncensored 24h peak of
**+2.7%**. Fees eat a third of the best case on the better arm and more of any
realised exit. That headwind is inherited by any family that trades this
universe at this frequency, whatever the signal. If family A is retired, family
B should either hold materially longer or fire far less often on higher
conviction — not re-enter the same wall with a different trigger.
