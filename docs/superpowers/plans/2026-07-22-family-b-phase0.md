# Family B Phase 0 — Gross-Edge Kill Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the pre-registered phase-0 entry-only replay for family B
(spec §5 of `docs/superpowers/specs/2026-07-20-yolo-family-b-momentum-continuation.md`,
APPROVED 2026-07-22): 81 entry cells × 2 arms × 3 horizons, modeled fills, gross
forward returns, and a selection-aware (max-statistic bootstrap) kill bar that must
clear the arm's full round trip.

**Architecture:** Two new pure-pandas/numpy modules under `scripts/path_analysis/`,
reusing the validated conventions already in the repo: universe ranking imported from
`scripts/rolling_backtest.py`, regime availability imported from
`scripts/verify_regime_gating.py`, seal-guard pattern copied from
`scripts/path_analysis/replay_family_a.py`. No freqtrade, no backtest, no strategy
edits — this is a read-only candle replay plus statistics.

**Tech Stack:** Python 3 (`.venv/bin/python3`), pandas, numpy, pytest. Data:
`user_data/data/kraken/*-15m.feather` already on disk (never download).

## Global Constraints

- **Holdout seal:** `SEAL_TS = 2025-09-01 UTC`. No candle with `ts >= SEAL_TS` may
  ever be read into a computation. Copy `replay_family_a.py`'s pattern: truncate
  every slice with `w = w[w.index < SEAL_TS]`, collect breaches, `sys.exit(1)` if
  any. Signals only in `2024-02-01 <= ts < 2025-09-01`.
- **No freqtrade runs, no data downloads, no edits** to
  `user_data/strategies/momentum_signals.py`, `MemeMomentum.py`, or
  `user_data/backtest_baseline_iter1/`. New files only (plus tests).
- **Grids (spec §3, pre-registered):** `ref_lookback` {48, 96, 192};
  `min_extension` {0.005, 0.01, 0.02}; `max_extension` {0.03, 0.04, 0.06};
  `volume_mult` {1.5, 2.0, 3.0}; `volume_window` fixed at 96. Full cross = 81
  cells; every `min_extension` < every `max_extension`, so **no cell is dropped as
  ill-formed** (state this in the report).
- **Horizons:** 24h/48h/96h = 96/192/384 15m bars.
- **Arms (spec §4):** L = `rank_pairs_for_month(DATA_DIR, month, 30)`;
  D = `rank_pairs_downcap_for_month(DATA_DIR, month)` — imported from
  `scripts/rolling_backtest.py`, never reimplemented. Round-trip hurdles:
  L 0.009, D 0.012. **Returns are GROSS** — fees appear only in the kill bar.
- **Regime (fail-closed):** import `regime_lookup_series()` from
  `scripts/verify_regime_gating.py` (BTC 15m → 1h via
  `momentum_signals.resample_1h`, `regime_mask_from_btc`, availability =
  bucket_open + 45m). A signal bar at `t` is in-regime iff the newest LUT row with
  `avail <= t` has `regime_ok == True`; no such row → False.
- **Determinism:** all randomness through `numpy.random.default_rng(20260722)`.

## Pre-registered analysis decisions (fixed before the run; log in backtests.md)

These fill gaps the spec leaves to implementation. Fixed NOW so the run can't
choose them after seeing results:

1. **Volume baseline includes the firing bar** —
   `vol_avg = volume.rolling(96).mean()` with no shift, matching family A's
   production convention in `momentum_signals.add_indicators`.
2. **Fill** = next 15m bar's open after the signal bar (same-pair next row).
   Veto if `fill > ref_high_signal × (1 + max_extension)` (frozen at the signal
   bar). Fills below the lower band are accepted. No next bar before the seal →
   entry dropped (counted).
3. **Forward return (gross)** = `exit_px / fill − 1`, where `exit_px` is the close
   of the last candle with `ts <= fill_ts + horizon` and `ts < SEAL_TS`. Excluded
   (never averaged in) and counted when: `fill_ts + horizon >= SEAL_TS`
   (seal-truncated) or elapsed data covers < 75% of the horizon (data gap).
4. **De-overlap, per (pair, cell, horizon):** after an accepted entry with fill at
   `t`, later signals for that pair/cell are skipped until `t + horizon` (greedy,
   chronological). Kills pseudo-replication from consecutive firing bars.
   Frequency numbers use the de-overlapped sets and stay labeled "unconstrained
   upper bound".
5. **Selection eligibility:** looks (cell × arm × horizon) with **n < 40** included
   entries are published but ineligible for selection — a 5-trade fluke must not
   win the argmax; 40 mirrors the holdout judgeability arithmetic (spec §6).
6. **Kill bar statistic:** month-clustered max-statistic bootstrap, B = 2000,
   months = calendar month of the signal bar (19 dev months).
   For each resample b: draw 19 months with replacement; a month drawn k times
   contributes its entries k times; compute `mean*_jb` for every eligible look j.
   `se_j` = std over b of `mean*_jb`. `q95` = 95th percentile over b of
   `max_j (mean*_jb − mean_j)/se_j`. Selected look s = argmax `mean_j` (eligible).
   **Lower bound = `mean_s − q95 × se_s`** (simultaneous/max-t bound — valid for
   the data-selected look). **PASS iff LB > round trip of s's arm.** Also report,
   transparency only: each arm's own best look with a per-arm max-t bound (max over
   that arm's looks), and the naive 5th percentile of the re-selected max.
7. **Path distribution** (sizes exits by amendment): for the selected look per arm
   — and always the default cell (96, 0.01, 0.04, 2.0) — over untruncated 96h
   windows: peak = `max(high)/fill − 1`, time-to-peak (h), pre-peak drawdown =
   `min(low)/fill − 1` up to the peak bar. Report p25/p50/p75/p90.
8. **Extension gradient:** pool the widest cell per lookback×volume pair is too
   sparse — use the single widest cell (`ref_lookback=96, min=0.005, max=0.06,
   volume_mult=2.0`), bucket entries by signal extension
   `close/ref_high − 1` into {0.5–1%, 1–1.5%, 1.5–2%, 2–3%, 3–4%, 4–6%}, report
   mean gross forward return and n per band × arm × horizon.
9. **Up-regime weeks** = (count of in-regime 1h buckets in the dev window) / 168.
   Trades/up-week = n_entries / that.

## File Structure

- Create `scripts/path_analysis/phase0_stats.py` — pure-numpy statistics: cell
  aggregation and the max-statistic bootstrap. No file I/O, fully unit-testable.
- Create `scripts/path_analysis/phase0_family_b.py` — signal math, fills,
  de-overlap, forward returns, universe/regime wiring, report + CSV output. CLI
  entry point.
- Create `tests/test_phase0_family_b.py` — all tests for both modules (repo
  convention: flat `tests/` dir).
- Modify `docs/backtests.md` — phase-0 log row BEFORE the run (done by the main
  session, not the implementer).

---

### Task 1: `phase0_stats.py` — max-statistic bootstrap

**Files:**
- Create: `scripts/path_analysis/phase0_stats.py`
- Test: `tests/test_phase0_family_b.py`

**Interfaces:**
- Produces:
  ```python
  def max_stat_bootstrap(
      looks: dict[str, dict[str, np.ndarray]],  # look_id -> {month "YYYY-MM" -> returns array}
      months: list[str],                        # the 19 dev months, fixed cluster list
      min_n: int = 40,
      n_boot: int = 2000,
      seed: int = 20260722,
  ) -> dict
  ```
  Returns `{"per_look": {look_id: {"n": int, "mean": float, "se": float,
  "eligible": bool}}, "selected": look_id | None, "lb_selected": float | None,
  "q95_max_t": float, "naive_p5_of_max": float}`.
  A look is eligible iff total n >= min_n. `selected` is the eligible argmax of
  mean. Degenerate guards: a look with `se == 0` is ineligible; if no look is
  eligible, `selected` is None (the gate then FAILS by definition).

- [ ] **Step 1: Write failing tests** — in `tests/test_phase0_family_b.py`:

```python
import numpy as np
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "path_analysis"))
from phase0_stats import max_stat_bootstrap

MONTHS = [f"2024-{m:02d}" for m in range(1, 11)]

def _look(rng, mu, n_per_month=20):
    return {m: rng.normal(mu, 0.03, n_per_month) for m in MONTHS}

def test_selection_picks_true_best_and_bound_is_below_mean():
    rng = np.random.default_rng(1)
    looks = {"good": _look(rng, 0.02), "zero": _look(rng, 0.0), "bad": _look(rng, -0.01)}
    out = max_stat_bootstrap(looks, MONTHS, min_n=40, n_boot=500, seed=7)
    assert out["selected"] == "good"
    assert out["lb_selected"] < out["per_look"]["good"]["mean"]

def test_selection_aware_bound_wider_than_naive_per_look():
    # 50 pure-noise looks: the max-t bound for the winner must sit further below
    # its mean than a plain 1.645*se bound would — that IS the selection penalty.
    rng = np.random.default_rng(2)
    looks = {f"n{i}": _look(rng, 0.0) for i in range(50)}
    out = max_stat_bootstrap(looks, MONTHS, min_n=40, n_boot=500, seed=7)
    sel = out["per_look"][out["selected"]]
    assert out["q95_max_t"] > 1.645
    assert out["lb_selected"] < sel["mean"] - 1.645 * sel["se"]

def test_pure_noise_winner_does_not_clear_zero():
    rng = np.random.default_rng(3)
    looks = {f"n{i}": _look(rng, 0.0) for i in range(50)}
    out = max_stat_bootstrap(looks, MONTHS, min_n=40, n_boot=500, seed=7)
    assert out["lb_selected"] < 0

def test_small_n_look_ineligible():
    rng = np.random.default_rng(4)
    looks = {"big": _look(rng, 0.001),
             "tiny_lucky": {MONTHS[0]: np.array([0.5] * 5)}}  # n=5, huge mean
    out = max_stat_bootstrap(looks, MONTHS, min_n=40, n_boot=200, seed=7)
    assert out["per_look"]["tiny_lucky"]["eligible"] is False
    assert out["selected"] == "big"

def test_deterministic():
    rng = np.random.default_rng(5)
    looks = {"a": _look(rng, 0.01), "b": _look(rng, 0.0)}
    o1 = max_stat_bootstrap(looks, MONTHS, n_boot=200, seed=7)
    o2 = max_stat_bootstrap(looks, MONTHS, n_boot=200, seed=7)
    assert o1["lb_selected"] == o2["lb_selected"]
```

- [ ] **Step 2: Run to verify failure** —
  `.venv/bin/pytest tests/test_phase0_family_b.py -v` → FAIL (import error).

- [ ] **Step 3: Implement** `scripts/path_analysis/phase0_stats.py`:

```python
"""Selection-aware statistics for family B phase 0 (spec s5, audit finding 1).

The gate tests the BEST of ~486 cell/arm/horizon looks, so an unadjusted
per-look confidence bound is near-vacuous. This module implements the
max-statistic (simultaneous / max-t) cluster bootstrap: resample calendar
months, compute every look's resampled mean, take the 95th percentile of the
max studentized deviation across looks, and back the selected look's mean off
by that amount. The resulting lower bound is valid for the data-selected look
because it is valid for ALL looks simultaneously.
"""
import numpy as np


def max_stat_bootstrap(looks, months, min_n=40, n_boot=2000, seed=20260722):
    rng = np.random.default_rng(seed)
    ids = sorted(looks)
    month_arrays = {j: {m: np.asarray(looks[j].get(m, []), dtype=float)
                        for m in months} for j in ids}
    n = {j: sum(len(a) for a in month_arrays[j].values()) for j in ids}
    mean = {j: (np.concatenate(list(month_arrays[j].values())).mean()
                if n[j] else np.nan) for j in ids}

    # bootstrap: resample the month list with replacement, all looks together
    boot = np.full((n_boot, len(ids)), np.nan)
    for b in range(n_boot):
        picks = rng.choice(len(months), size=len(months), replace=True)
        for k, j in enumerate(ids):
            arrs = [month_arrays[j][months[p]] for p in picks]
            flat = np.concatenate(arrs) if arrs else np.array([])
            if len(flat):
                boot[b, k] = flat.mean()

    se = {j: float(np.nanstd(boot[:, k], ddof=1)) for k, j in enumerate(ids)}
    eligible = {j: bool(n[j] >= min_n and se[j] > 0 and np.isfinite(mean[j]))
                for j in ids}
    elig_idx = [k for k, j in enumerate(ids) if eligible[j]]

    out = {"per_look": {j: {"n": n[j], "mean": float(mean[j]), "se": se[j],
                            "eligible": eligible[j]} for j in ids},
           "selected": None, "lb_selected": None,
           "q95_max_t": float("nan"), "naive_p5_of_max": float("nan")}
    if not elig_idx:
        return out

    sub = boot[:, elig_idx]
    centers = np.array([mean[ids[k]] for k in elig_idx])
    ses = np.array([se[ids[k]] for k in elig_idx])
    t_max = np.nanmax((sub - centers) / ses, axis=1)
    q95 = float(np.nanpercentile(t_max, 95))
    sel_k = elig_idx[int(np.nanargmax(centers))]
    sel = ids[sel_k]
    out["selected"] = sel
    out["q95_max_t"] = q95
    out["lb_selected"] = float(mean[sel] - q95 * se[sel])
    out["naive_p5_of_max"] = float(np.nanpercentile(np.nanmax(sub, axis=1), 5))
    return out
```

- [ ] **Step 4: Run tests** → all 5 PASS. Also run the full suite
  (`.venv/bin/pytest tests/ -q`) → 37 + 5 pass, nothing broken.

- [ ] **Step 5: Commit** — `git add scripts/path_analysis/phase0_stats.py
  tests/test_phase0_family_b.py && git commit -m "Family B phase 0: selection-aware
  max-statistic bootstrap"`

### Task 2: signal math — per-cell entry masks

**Files:**
- Create: `scripts/path_analysis/phase0_family_b.py`
- Test: `tests/test_phase0_family_b.py` (append)

**Interfaces:**
- Produces (consumed by Tasks 3–4):
  ```python
  REF_LOOKBACKS = (48, 96, 192)
  MIN_EXTS = (0.005, 0.01, 0.02)
  MAX_EXTS = (0.03, 0.04, 0.06)
  VOL_MULTS = (1.5, 2.0, 3.0)
  VOLUME_WINDOW = 96
  HORIZON_BARS = {"24h": 96, "48h": 192, "96h": 384}
  SEAL_TS, DEV_START  # pd.Timestamps, UTC

  def compute_features(df: pd.DataFrame) -> pd.DataFrame
      # adds ref_high_{48,96,192} = high.rolling(n).max().shift(1)
      # and vol_avg = volume.rolling(96).mean()  (firing bar INCLUDED, family-A convention)

  def cell_mask(df, ref_lookback, min_ext, max_ext, volume_mult, regime: pd.Series) -> pd.Series
      # close >= ref_high*(1+min_ext)  AND  close <= ref_high*(1+max_ext)
      # AND volume >= volume_mult*vol_avg (vol_avg notna) AND regime; NaN -> False
  ```
  `df` is indexed by UTC timestamp with columns open/high/low/close/volume.
  `regime` is a bool Series aligned to `df.index`.

- [ ] **Step 1: Failing tests** — synthetic 15m frame builder + cases:

```python
import pandas as pd
from phase0_family_b import (compute_features, cell_mask, REF_LOOKBACKS)

def _frame(closes, highs=None, vols=None, start="2024-06-01"):
    idx = pd.date_range(start, periods=len(closes), freq="15min", tz="UTC")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"open": c, "high": highs if highs is not None else c,
                         "low": c, "close": c,
                         "volume": vols if vols is not None else [100.0] * len(c)},
                        index=idx)

def test_ref_high_excludes_firing_bar():
    # 50 flat bars at 100, then a bar closing 102: ref_high_48 must be 100
    # (prior bars only), so extension = 2%.
    df = compute_features(_frame([100.0] * 50 + [102.0]))
    assert df["ref_high_48"].iloc[-1] == 100.0

def test_band_bounds_inclusive():
    df = compute_features(_frame([100.0] * 50 + [101.0]))   # exactly +1%
    on = pd.Series(True, index=df.index)
    assert cell_mask(df, 48, 0.01, 0.04, 1.0, on).iloc[-1]          # >= min: fires
    assert not cell_mask(df, 48, 0.02, 0.04, 1.0, on).iloc[-1]      # below min
    df4 = compute_features(_frame([100.0] * 50 + [104.0]))  # exactly +4%
    assert cell_mask(df4, 48, 0.01, 0.04, 1.0, on).iloc[-1]         # <= max: fires
    df5 = compute_features(_frame([100.0] * 50 + [105.0]))
    assert not cell_mask(df5, 48, 0.01, 0.04, 1.0, on).iloc[-1]     # above max

def test_volume_gate_and_regime_fail_closed():
    vols = [100.0] * 50 + [150.0]                            # 1.5x baseline-ish
    df = compute_features(_frame([100.0] * 50 + [102.0], vols=vols))
    on = pd.Series(True, index=df.index)
    off = pd.Series(False, index=df.index)
    assert not cell_mask(df, 48, 0.01, 0.04, 3.0, on).iloc[-1]      # volume too low
    assert not cell_mask(df, 48, 0.01, 0.04, 1.0, off).iloc[-1]     # regime off
    assert not cell_mask(df, 48, 0.01, 0.04, 1.0, on).iloc[:49].any()  # warmup NaN -> False
```

- [ ] **Step 2: Run** → FAIL (module missing).
- [ ] **Step 3: Implement** the constants + two functions (vectorized, ~30 lines;
  mirror `momentum_signals.add_indicators`'s shift(1) idiom; `mask.fillna(False)`).
- [ ] **Step 4: Run tests** → PASS; full suite still green.
- [ ] **Step 5: Commit** — "Family B phase 0: per-cell entry masks".

### Task 3: fills, veto, de-overlap, forward returns, seal guard

**Files:**
- Modify: `scripts/path_analysis/phase0_family_b.py`
- Test: `tests/test_phase0_family_b.py` (append)

**Interfaces:**
- Produces:
  ```python
  def entries_for_cell(df, mask, ref_col, max_ext, horizon_bars, seal_breach: list) -> pd.DataFrame
      # columns: signal_ts, fill_ts, fill, fwd_ret, month (of signal_ts),
      #          extension (signal close/ref_high - 1)
      # plus attrs counts: vetoed, no_fill, seal_truncated, gap_excluded
  ```
  Rules (pre-registered decisions 2–4 above): fill = next bar's open; veto if
  fill > ref_high(signal)*(1+max_ext); exit price = close of last candle with
  ts <= fill_ts + horizon and ts < SEAL_TS; exclude+count if horizon crosses the
  seal or <75% of horizon covered; greedy de-overlap — skip signals until the
  previous accepted entry's fill_ts + horizon. Any read at/after SEAL_TS appends
  to `seal_breach`.

- [ ] **Step 1: Failing tests**:

```python
from phase0_family_b import entries_for_cell, SEAL_TS

def test_fill_is_next_open_and_gap_veto():
    # signal bar closes at 102 (+2% over ref 100); next bar opens at 105 —
    # above the 104 cap -> vetoed. A second signal whose next open is 103 fills.
    ...  # build with _frame(), assert one entry, fill == 103, attrs["vetoed"] == 1

def test_deoverlap_skips_signals_inside_horizon():
    # mask fires on 10 consecutive bars; horizon 96 bars -> exactly 1 entry.

def test_forward_return_open_to_close_at_horizon():
    # constant prices then a known ramp: fwd_ret == expected close/fill - 1.

def test_seal_truncation_excluded_and_counted():
    # entry whose fill_ts + horizon lands past 2025-09-01 -> no fwd_ret,
    # attrs["seal_truncated"] == 1, and seal_breach stays empty (guard held).
```

Write these four tests in full (each ~8 lines with `_frame`).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `entries_for_cell` (~45 lines): iterate signal
  timestamps chronologically (they are sparse — loop is fine), positional
  `df.index.get_loc` for next-bar fill, slice `df.iloc[fill_pos : fill_pos +
  horizon_bars + 1]` then apply `w = w[w.index < SEAL_TS]` + breach check
  exactly as `replay_family_a.window_for` does.
- [ ] **Step 4: Run tests** → PASS; full suite green.
- [ ] **Step 5: Commit** — "Family B phase 0: fills, de-overlap, seal-guarded
  forward returns".

### Task 4: universe + regime wiring, aggregation, report CLI

**Files:**
- Modify: `scripts/path_analysis/phase0_family_b.py`
- Test: `tests/test_phase0_family_b.py` (append)

**Interfaces:**
- Consumes: `rank_pairs_for_month`, `rank_pairs_downcap_for_month`, `DATA_DIR`
  from `scripts/rolling_backtest.py`; `regime_lookup_series` from
  `scripts/verify_regime_gating.py` (add both script dirs to `sys.path` at module
  top, the way `verify_regime_gating.py` itself imports `momentum_signals`).
- Produces:
  ```python
  def build_universe(months) -> dict[tuple[str, str], set[str]]   # (arm, "YYYY-MM") -> pairs
  def regime_series_for(index: pd.DatetimeIndex, lut) -> pd.Series  # merge_asof on avail
  def main() -> None   # CLI: assembles everything, prints report, writes CSV
  ```
- `main()` flow: months = 2024-02..2025-08; build universe; union of pairs;
  per pair: load feather once (cache), `compute_features`, regime series; per
  (arm, cell): concat `entries_for_cell` output restricted to months where the
  pair is in that arm's whitelist (restrict by signal_ts month BEFORE
  de-overlap, i.e. pass per-month masked signal sets — simplest correct: run
  `entries_for_cell` on the pair's full mask AND month-membership mask); per
  horizon: look_id = f"{arm}|{cell}|{horizon}". Feed all looks to
  `max_stat_bootstrap(min_n=40, n_boot=2000, seed=20260722)`. Print: verdict
  block (selected look, mean, se, q95, LB vs arm round trip → PASS/FAIL), per-arm
  best look with per-arm max-t bound, top-20 cell table, extension gradient
  (decision 8), path distribution (decision 7), frequency per up-week
  (decision 9, labeled unconstrained upper bound), exclusion counts, seal-guard
  OK line. Write every look's row (n, mean, se, eligible, trades/up-week) to
  `docs/diagnostics/2026-07-22-family-b-phase0-cells.csv`.
- [ ] **Step 1: Failing test** — one integration test on a synthetic mini-universe:
  monkeypatch `build_universe` to a fixed dict and candle loading to two synthetic
  pairs; assert `main()`-level aggregation produces a CSV with 81 × 2 × 3 rows and
  a verdict line (capsys). Keep it to the aggregation seams — the statistical and
  entry logic is already unit-tested.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (~120 lines). **Step 4:** tests
  PASS; full suite green. **Step 5: Commit** — "Family B phase 0: universe wiring,
  aggregation, report".

### Task 5: log, run, verify, write up (MAIN SESSION — not the implementer)

- [ ] Add the phase-0 row (hypothesis + falsifier) to `docs/backtests.md` DEV
  table BEFORE the run, including the pre-registered decisions 1–9 above.
- [ ] Run `.venv/bin/python3 scripts/path_analysis/phase0_family_b.py | tee
  docs/diagnostics/2026-07-22-family-b-phase0.txt`.
- [ ] Verify: seal-guard OK line printed; exclusion counts sane; entry counts vs
  family A's magnitude sanity check; spot-check one entry by hand against raw
  candles (fill, veto, forward return).
- [ ] Record the verdict in `docs/backtests.md`; if PASS → the selected cell
  becomes the iteration-1 baseline and exits get sized from the path distribution
  by spec amendment; if FAIL on the kill bar → family B dies at zero iterations,
  holdout stays sealed. Report to Austin either way. Commit everything.

## Self-review (done)

- Spec §5 coverage: 81-cell cross ✓ (all valid, stated), modeled-fill forward
  returns ✓ (decision 2–3), band veto ✓, per-cell publication ✓ (CSV + top-20),
  per-band gradient ✓ (decision 8), frequency upper bound ✓ (decision 9), path
  distribution ✓ (decision 7), max-statistic kill bar vs full round trip ✓
  (decision 6, Task 1), selection rule disclosed ✓, seal intact ✓.
- Gaps the spec left open are pinned as pre-registered decisions 1–9, logged
  before the run — not chosen after seeing results.
- Type consistency: `looks` dict shape matches between Task 1 and Task 4;
  `entries_for_cell` month column feeds the bootstrap's cluster key.
