"""Family B phase 0 -- gross-edge kill gate (spec s5,
docs/superpowers/specs/2026-07-20-yolo-family-b-momentum-continuation.md).

Entry-only replay: 81 cells (ref_lookback x min_extension x max_extension x
volume_mult) x 2 arms (L, D) x 3 horizons (24h/48h/96h). Modeled fills, GROSS
forward returns (fees appear only in the kill bar), and a selection-aware
max-statistic bootstrap (phase0_stats.max_stat_bootstrap) that must clear the
arm's full round trip before this family gets an iteration. No freqtrade, no
strategy edits -- a read-only candle replay plus statistics.

HOLDOUT SEAL (hard constraint, spec s5): no candle at/after SEAL_TS may ever
be read. Every window is truncated the way replay_family_a.window_for does,
and a breach anywhere aborts the run.

Pre-registered analysis decisions 1-9 (plan
docs/superpowers/plans/2026-07-22-family-b-phase0.md) are implemented exactly
as fixed there -- see per-function docstrings for which decision each rule
maps to.
"""
import sys
import warnings
from pathlib import Path

# The pyarrow feather deprecation fires once per file read; thousands of reads
# would swamp the diagnostic artifact (replay_family_a.py does the same).
warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))
from rolling_backtest import (  # noqa: E402
    DATA_DIR, rank_pairs_for_month, rank_pairs_downcap_for_month,
)
from verify_regime_gating import regime_lookup_series  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
from phase0_stats import max_stat_bootstrap  # noqa: E402

# --- grids (spec s3, pre-registered) ----------------------------------------
REF_LOOKBACKS = (48, 96, 192)
MIN_EXTS = (0.005, 0.01, 0.02)
MAX_EXTS = (0.03, 0.04, 0.06)
VOL_MULTS = (1.5, 2.0, 3.0)
VOLUME_WINDOW = 96
HORIZON_BARS = {"24h": 96, "48h": 192, "96h": 384}
# Full cross = 81 cells; every min_extension < every max_extension, so no
# cell is ill-formed and none is dropped.
CELLS = [(rl, mn, mx, vm) for rl in REF_LOOKBACKS for mn in MIN_EXTS
         for mx in MAX_EXTS for vm in VOL_MULTS]

# --- holdout seal ------------------------------------------------------------
SEAL_TS = pd.Timestamp("2025-09-01", tz="UTC")
DEV_START = pd.Timestamp("2024-02-01", tz="UTC")
DEV_END = pd.Timestamp("2025-08-01", tz="UTC")  # last month START in the dev range

# --- arms (spec s4): full round-trip cost the kill bar must clear -----------
ROUND_TRIP = {"L": 0.009, "D": 0.012}

CSV_OUT = Path("docs/diagnostics/2026-07-22-family-b-phase0-cells.csv")


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """ref_high_{48,96,192} = high.rolling(n).max().shift(1) (firing bar
    excluded, mirroring momentum_signals.add_indicators's shift(1) idiom).

    vol_avg = volume.rolling(96).mean() WITH THE FIRING BAR INCLUDED (decision
    1 -- no shift, matching family A's production convention). min_periods=1
    only affects warmup bars with under 96 candles of history; every pair in
    the real run has a full prior month on disk before it enters a universe
    month, so vol_avg is fully formed before any counted signal -- identical
    real-world results either way, but the shorter synthetic test frames need
    it to avoid an all-NaN warmup swallowing every fixture.
    """
    df = df.copy()
    for n in REF_LOOKBACKS:
        df[f"ref_high_{n}"] = df["high"].rolling(n).max().shift(1)
    df["vol_avg"] = df["volume"].rolling(VOLUME_WINDOW, min_periods=1).mean()
    return df


def cell_mask(df: pd.DataFrame, ref_lookback: int, min_ext: float, max_ext: float,
              volume_mult: float, regime: pd.Series) -> pd.Series:
    """close >= ref_high*(1+min_ext) AND close <= ref_high*(1+max_ext)
    AND volume >= volume_mult*vol_avg (vol_avg notna) AND regime; NaN -> False."""
    ref_high = df[f"ref_high_{ref_lookback}"]
    band_ok = (df["close"] >= ref_high * (1 + min_ext)) & \
              (df["close"] <= ref_high * (1 + max_ext))
    volume_ok = df["vol_avg"].notna() & \
        (df["volume"] >= volume_mult * df["vol_avg"])
    regime_aligned = regime.reindex(df.index).fillna(False).astype(bool)
    mask = band_ok & volume_ok & regime_aligned
    return mask.fillna(False)


_ENTRY_COLUMNS = ["signal_ts", "fill_ts", "fill", "fwd_ret", "month", "extension", "pair"]


def entries_for_cell(df: pd.DataFrame, mask: pd.Series, ref_col: str,
                     max_ext: float, horizon_bars: int,
                     seal_breach: list) -> pd.DataFrame:
    """Walk signal bars chronologically, applying decisions 2-4 in order:

    2. Fill = next bar's OPEN. Veto if fill > ref_high(signal_bar)*(1+max_ext)
       (the cap is frozen at the signal bar, never a later one). No next bar
       before the seal -> dropped (attrs["no_fill"]).
    3. Forward return = exit_px/fill - 1, exit_px = close of the last candle
       with ts <= fill_ts + horizon and ts < SEAL_TS. Excluded (fwd_ret = NaN)
       and counted, never averaged in, when the horizon crosses the seal
       (attrs["seal_truncated"]) or elapsed data covers < 75% of the horizon
       (attrs["gap_excluded"]) -- coverage is measured as elapsed TIME span
       (w.index.max() - fill_ts) vs the horizon duration, not a bar count,
       since a seal/frame-edge cut only ever shortens the tail.
    4. De-overlap: after an ACCEPTED entry with fill at t, later signals are
       skipped until t + horizon (greedy, chronological). A vetoed or
       no-fill signal does NOT advance the watermark -- only an accepted
       entry does (decision 4's own wording).

    The seal-guard slice mirrors replay_family_a.window_for exactly: slice
    positionally, then `w = w[w.index < SEAL_TS]`, then flag a breach if any
    candle in the raw positional slice reached the seal.
    """
    horizon_td = pd.Timedelta(minutes=15 * horizon_bars)
    positions = np.flatnonzero(mask.to_numpy())
    rows = []
    vetoed = no_fill = seal_truncated = gap_excluded = 0
    next_allowed_ts = None

    for pos in positions:
        signal_ts = df.index[pos]
        if next_allowed_ts is not None and signal_ts < next_allowed_ts:
            continue  # de-overlap: still inside the previous accepted entry's horizon

        fill_pos = pos + 1
        if fill_pos >= len(df):
            no_fill += 1
            continue

        fill_ts = df.index[fill_pos]
        fill_px = float(df["open"].iloc[fill_pos])
        ref_high_signal = float(df[ref_col].iloc[pos])
        cap = ref_high_signal * (1 + max_ext)
        if fill_px > cap:
            vetoed += 1
            continue

        exit_end = fill_ts + horizon_td
        w = df.iloc[fill_pos: fill_pos + horizon_bars + 1]
        w = w[w.index < SEAL_TS]
        if len(w) and w.index.max() >= SEAL_TS:
            seal_breach.append(f"signal {signal_ts} fill {fill_ts}")

        if exit_end >= SEAL_TS:
            fwd_ret = float("nan")
            seal_truncated += 1
        else:
            covered = (w.index.max() - fill_ts) if len(w) else pd.Timedelta(0)
            if not len(w) or covered < 0.75 * horizon_td:
                fwd_ret = float("nan")
                gap_excluded += 1
            else:
                exit_px = float(w["close"].iloc[-1])
                fwd_ret = exit_px / fill_px - 1

        rows.append({
            "signal_ts": signal_ts, "fill_ts": fill_ts, "fill": fill_px,
            "fwd_ret": fwd_ret, "month": f"{signal_ts:%Y-%m}",
            "extension": df["close"].iloc[pos] / ref_high_signal - 1,
        })
        next_allowed_ts = exit_end  # watermark advances only on an accepted entry

    out = pd.DataFrame(rows, columns=_ENTRY_COLUMNS)
    out.attrs["vetoed"] = vetoed
    out.attrs["no_fill"] = no_fill
    out.attrs["seal_truncated"] = seal_truncated
    out.attrs["gap_excluded"] = gap_excluded
    return out


def _cell_id(cell: tuple) -> str:
    rl, mn, mx, vm = cell
    return f"{rl}-{mn}-{mx}-{vm}"


WIDEST_CELL_ID = _cell_id((96, 0.005, 0.06, 2.0))
DEFAULT_CELL_ID = _cell_id((96, 0.01, 0.04, 2.0))


def top20_table(per_look: dict, trades_per_up_week: dict, top_n: int = 20) -> pd.DataFrame:
    """Plan Task 4 publication requirement: every eligible look, sorted by
    mean descending, top N. look_id, n, mean, se, trades/up-week."""
    rows = [
        {"look_id": look_id, "n": st["n"], "mean": st["mean"], "se": st["se"],
         "trades_per_up_week": trades_per_up_week.get(look_id, float("nan"))}
        for look_id, st in per_look.items() if st["eligible"]
    ]
    cols = ["look_id", "n", "mean", "se", "trades_per_up_week"]
    df = pd.DataFrame(rows, columns=cols)
    return df.sort_values("mean", ascending=False).head(top_n).reset_index(drop=True)


# Extension gradient bands (decision 8): pre-registered, left-closed/right-open
# except the last band, which is closed on both ends.
_EXTENSION_BANDS = [
    (0.005, 0.01, False),
    (0.01, 0.015, False),
    (0.015, 0.02, False),
    (0.02, 0.03, False),
    (0.03, 0.04, False),
    (0.04, 0.06, True),
]


def _band_label(lo: float, hi: float, right_inclusive: bool) -> str:
    return f"[{lo},{hi}{']' if right_inclusive else ')'}"


_EXTENSION_BAND_LABELS = [_band_label(*b) for b in _EXTENSION_BANDS]


def _assign_band(ext: float):
    for lo, hi, incl in _EXTENSION_BANDS:
        if ext >= lo and (ext < hi or (incl and ext <= hi)):
            return _band_label(lo, hi, incl)
    return None  # outside the pre-registered range -- dropped, not merged in


def extension_gradient(entries: pd.DataFrame) -> pd.DataFrame:
    """Decision 8: bucket each entry's `extension` into the pre-registered
    bands and report n / mean gross fwd_ret per arm x horizon x band. `n` and
    the mean are both over valid (non-NaN fwd_ret) entries only -- an entry
    excluded from every other average (seal-truncated/gap) is excluded here
    too. `entries` must carry columns extension, fwd_ret, arm, horizon
    (already concatenated by the caller from the widest cell's looks)."""
    e = entries.copy()
    e["band"] = e["extension"].map(_assign_band)
    e = e[e["band"].notna()]
    valid = e.dropna(subset=["fwd_ret"])
    if not len(valid):
        return pd.DataFrame(columns=["arm", "horizon", "band", "n", "mean"])
    grouped = (valid.groupby(["arm", "horizon", "band"], observed=True)["fwd_ret"]
               .agg(n="size", mean="mean").reset_index())
    grouped["band"] = pd.Categorical(grouped["band"], categories=_EXTENSION_BAND_LABELS,
                                     ordered=True)
    return grouped.sort_values(["arm", "horizon", "band"]).reset_index(drop=True)


def path_stats(df: pd.DataFrame, entries: pd.DataFrame,
               horizon_bars: int = 384) -> pd.DataFrame:
    """Decision 7: per-entry path shape over the (always 96h) window, seal-
    guarded the same way entries_for_cell's exit window is. For each entry:
    peak = max(high)/fill - 1; time_to_peak_h = hours from fill to the peak
    bar; pre_peak_drawdown = min(low) from the fill bar through the peak bar
    (inclusive), /fill - 1. Returns one row per entry; the caller aggregates
    quantiles across the population it has already restricted to untruncated
    entries (dropna(fwd_ret) on the matching 96h look)."""
    rows = []
    for _, e in entries.iterrows():
        fill_ts = e["fill_ts"]
        fill_px = float(e["fill"])
        pos = df.index.get_loc(fill_ts)
        w = df.iloc[pos: pos + horizon_bars + 1]
        w = w[w.index < SEAL_TS]
        if not len(w):
            continue
        peak_idx = w["high"].idxmax()
        peak_px = float(w.loc[peak_idx, "high"])
        pre_peak_low = float(w.loc[:peak_idx, "low"].min())
        rows.append({
            "fill_ts": fill_ts,
            "peak": peak_px / fill_px - 1,
            "time_to_peak_h": (peak_idx - fill_ts).total_seconds() / 3600.0,
            "pre_peak_drawdown": pre_peak_low / fill_px - 1,
        })
    return pd.DataFrame(rows, columns=["fill_ts", "peak", "time_to_peak_h",
                                       "pre_peak_drawdown"])


def build_universe(months: list) -> dict:
    """(arm, "YYYY-MM") -> set of whitelisted pairs, spec s4 (imported, never
    reimplemented): L = rank_pairs_for_month(DATA_DIR, month, 30);
    D = rank_pairs_downcap_for_month(DATA_DIR, month)."""
    universe = {}
    for m in months:
        key = f"{m:%Y-%m}"
        universe[("L", key)] = set(rank_pairs_for_month(DATA_DIR, m, 30))
        universe[("D", key)] = set(rank_pairs_downcap_for_month(DATA_DIR, m))
    return universe


def regime_series_for(index: pd.DatetimeIndex, lut: pd.DataFrame) -> pd.Series:
    """Merge-asof a signal-bar index against the BTC regime LUT: in-regime
    iff the newest LUT row with avail <= t has regime_ok == True; no such row
    -> False (fail-closed, spec s4).

    Both keys are normalized to ns resolution first: pair feathers load as
    datetime64[ms, UTC] while the LUT computes as [us, UTC], and merge_asof
    refuses mixed units. The result is re-indexed by the CALLER's original
    index object (same order as the sorted merge, asserted), so downstream
    `regime.reindex(df.index)` in cell_mask aligns exactly — a unit-mismatched
    index there would silently produce all-False."""
    idx_ns = pd.DatetimeIndex(index).as_unit("ns")
    idx_df = pd.DataFrame({"ts": idx_ns}).sort_values("ts")
    lut_ns = lut.assign(avail=lut["avail"].dt.as_unit("ns")).sort_values("avail")
    merged = pd.merge_asof(idx_df, lut_ns,
                           left_on="ts", right_on="avail", direction="backward")
    regime = merged["regime_ok"].fillna(False).astype(bool)
    assert (merged["ts"].to_numpy() == idx_ns.to_numpy()).all(), \
        "signal index must be pre-sorted so merge order matches the caller's index"
    return pd.Series(regime.to_numpy(), index=index)


_candle_cache: dict = {}


def load_candles(pair: str) -> pd.DataFrame:
    """Load one pair's 15m feather once, cached (replay_family_a.candles's
    pattern). No seal enforcement here -- main() truncates before use."""
    if pair not in _candle_cache:
        df = pd.read_feather(DATA_DIR / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        _candle_cache[pair] = df.set_index("date").sort_index()
    return _candle_cache[pair]


def main() -> None:
    months = list(pd.date_range(DEV_START, DEV_END, freq="MS", tz="UTC"))
    month_strs = [f"{m:%Y-%m}" for m in months]
    universe = build_universe(months)
    all_pairs = sorted({p for pairs in universe.values() for p in pairs})

    lut = regime_lookup_series()
    lut = lut[lut["avail"] < SEAL_TS]  # seal guard, symmetric with the candle truncation below
    up_regime_buckets = int(((lut["avail"] >= DEV_START) & lut["regime_ok"]).sum())
    up_regime_weeks = up_regime_buckets / 168.0

    seal_breach: list = []
    entries_by_look: dict = {}
    exclude_totals = {"vetoed": 0, "no_fill": 0, "seal_truncated": 0, "gap_excluded": 0}

    for pair in all_pairs:
        df = load_candles(pair)
        df = df[df.index < SEAL_TS]  # never let a sealed candle reach a computation
        if not len(df):
            continue
        df = compute_features(df)
        regime = regime_series_for(df.index, lut)
        month_of_bar = df.index.strftime("%Y-%m")
        arm_month_masks = {}
        for arm in ("L", "D"):
            membership = {m: (pair in universe.get((arm, m), set())) for m in month_strs}
            arm_month_masks[arm] = pd.Series(
                pd.Series(month_of_bar, index=df.index).map(membership).fillna(False),
                dtype=bool)

        for cell in CELLS:
            base_mask = cell_mask(df, *cell, regime)
            if not base_mask.any():
                continue
            for arm in ("L", "D"):
                masked = base_mask & arm_month_masks[arm]
                if not masked.any():
                    continue
                for horizon_label, horizon_bars in HORIZON_BARS.items():
                    entries = entries_for_cell(df, masked, f"ref_high_{cell[0]}",
                                               cell[2], horizon_bars, seal_breach)
                    entries["pair"] = pair
                    for k in exclude_totals:
                        exclude_totals[k] += entries.attrs[k]
                    look_id = f"{arm}|{_cell_id(cell)}|{horizon_label}"
                    entries_by_look.setdefault(look_id, []).append(entries)

    if seal_breach:
        print(f"SEAL BREACH -- {len(seal_breach)} windows reached the holdout:")
        print("\n".join("  " + b for b in seal_breach[:10]))
        sys.exit(1)
    print(f"Seal guard OK: no candle at/after {SEAL_TS:%Y-%m-%d} read.")

    looks, rows_for_csv = {}, []
    for arm in ("L", "D"):
        for cell in CELLS:
            for horizon_label in HORIZON_BARS:
                look_id = f"{arm}|{_cell_id(cell)}|{horizon_label}"
                dfs = entries_by_look.get(look_id, [])
                all_e = (pd.concat(dfs, ignore_index=True) if dfs
                        else pd.DataFrame(columns=_ENTRY_COLUMNS))
                valid = all_e.dropna(subset=["fwd_ret"])
                looks[look_id] = {m: valid.loc[valid["month"] == m, "fwd_ret"].to_numpy()
                                  for m in month_strs}
                total_entries = len(all_e)
                rows_for_csv.append({
                    "arm": arm, "ref_lookback": cell[0], "min_ext": cell[1],
                    "max_ext": cell[2], "volume_mult": cell[3], "horizon": horizon_label,
                    "look_id": look_id, "total_entries": total_entries,
                    "trades_per_up_week": (total_entries / up_regime_weeks
                                          if up_regime_weeks else float("nan")),
                })

    result = max_stat_bootstrap(looks, month_strs, min_n=40, n_boot=2000, seed=20260722)
    stats_by_look = result["per_look"]
    for row in rows_for_csv:
        st = stats_by_look[row["look_id"]]
        row.update({"n": st["n"], "mean": st["mean"], "se": st["se"],
                   "eligible": st["eligible"]})

    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_for_csv).to_csv(CSV_OUT, index=False)

    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    selected = result["selected"]
    if selected is None:
        print("No look reached the n>=40 eligibility bar -- gate FAILS by definition.")
    else:
        arm = selected.split("|")[0]
        hurdle = ROUND_TRIP[arm]
        lb = result["lb_selected"]
        verdict = "PASS" if lb > hurdle else "FAIL"
        sel_stats = stats_by_look[selected]
        print(f"Selected look: {selected}  (n={sel_stats['n']})")
        print(f"  mean={sel_stats['mean']:+.4%} se={sel_stats['se']:.4%} "
              f"q95_max_t={result['q95_max_t']:.3f}")
        print(f"  LB={lb:+.4%} vs arm {arm} round trip {hurdle:.3%} -> {verdict}")
        print(f"  naive (unadjusted) 5th pct of re-selected max: "
              f"{result['naive_p5_of_max']:+.4%}")

    for arm in ("L", "D"):
        arm_looks = {k: v for k, v in looks.items() if k.startswith(f"{arm}|")}
        arm_result = max_stat_bootstrap(arm_looks, month_strs, min_n=40,
                                        n_boot=2000, seed=20260722)
        if arm_result["selected"]:
            sel = arm_result["selected"]
            print(f"  arm {arm} best look (own max-t bound): {sel} "
                  f"mean={arm_result['per_look'][sel]['mean']:+.4%} "
                  f"LB={arm_result['lb_selected']:+.4%}")
        else:
            print(f"  arm {arm}: no eligible look")

    trades_per_up_week = {row["look_id"]: row["trades_per_up_week"] for row in rows_for_csv}
    print("\n" + "=" * 78)
    print("TOP-20 LOOKS BY MEAN (eligible only)")
    print("=" * 78)
    for _, r in top20_table(stats_by_look, trades_per_up_week, top_n=20).iterrows():
        print(f"  {r['look_id']:<30} n={int(r['n']):>5} mean={r['mean']:+.4%} "
              f"se={r['se']:.4%} trades/up-week={r['trades_per_up_week']:.3f}")

    print("\n" + "=" * 78)
    print(f"EXTENSION GRADIENT (decision 8, widest cell {WIDEST_CELL_ID})")
    print("=" * 78)
    gradient_frames = []
    for arm in ("L", "D"):
        for horizon_label in HORIZON_BARS:
            dfs = entries_by_look.get(f"{arm}|{WIDEST_CELL_ID}|{horizon_label}", [])
            if not dfs:
                continue
            combined = pd.concat(dfs, ignore_index=True)
            combined["arm"] = arm
            combined["horizon"] = horizon_label
            gradient_frames.append(combined)
    gradient_entries = (pd.concat(gradient_frames, ignore_index=True) if gradient_frames
                        else pd.DataFrame(columns=_ENTRY_COLUMNS + ["arm", "horizon"]))
    for _, r in extension_gradient(gradient_entries).iterrows():
        print(f"  {r['arm']} {r['horizon']:>3} {r['band']:<14} n={int(r['n']):>5} "
              f"mean_fwd_ret={r['mean']:+.4%}")

    print("\n" + "=" * 78)
    print("PATH DISTRIBUTION (decision 7, 96h de-overlapped, untruncated entries)")
    print("=" * 78)
    path_targets = []
    if selected is not None:
        sel_cell_id = selected.split("|")[1]
        if sel_cell_id == DEFAULT_CELL_ID:
            path_targets.append((DEFAULT_CELL_ID, "selected+default"))
        else:
            path_targets.append((sel_cell_id, "selected"))
            path_targets.append((DEFAULT_CELL_ID, "default"))
    else:
        path_targets.append((DEFAULT_CELL_ID, "default"))

    for cell_id, label in path_targets:
        print(f"  cell {cell_id} [{label}]")
        for arm in ("L", "D"):
            dfs = entries_by_look.get(f"{arm}|{cell_id}|96h", [])
            all_e = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
            valid = all_e.dropna(subset=["fwd_ret"]) if len(all_e) else all_e
            if not len(valid):
                print(f"    arm {arm}: no untruncated 96h entries")
                continue
            per_entry_frames = []
            for pair, group in valid.groupby("pair"):
                pair_df = load_candles(pair)
                pair_df = pair_df[pair_df.index < SEAL_TS]
                per_entry_frames.append(path_stats(pair_df, group, horizon_bars=384))
            per_entry = (pd.concat(per_entry_frames, ignore_index=True)
                        if per_entry_frames else pd.DataFrame())
            if not len(per_entry):
                print(f"    arm {arm}: no untruncated 96h entries")
                continue
            qs = [0.25, 0.5, 0.75, 0.9]
            pk = per_entry["peak"].quantile(qs)
            tp = per_entry["time_to_peak_h"].quantile(qs)
            dd = per_entry["pre_peak_drawdown"].quantile(qs)
            print(f"    arm {arm} n={len(per_entry)}")
            print(f"      peak            p25={pk[0.25]:+.4%} p50={pk[0.5]:+.4%} "
                  f"p75={pk[0.75]:+.4%} p90={pk[0.9]:+.4%}")
            print(f"      time_to_peak_h  p25={tp[0.25]:.2f} p50={tp[0.5]:.2f} "
                  f"p75={tp[0.75]:.2f} p90={tp[0.9]:.2f}")
            print(f"      pre_peak_dd     p25={dd[0.25]:+.4%} p50={dd[0.5]:+.4%} "
                  f"p75={dd[0.75]:+.4%} p90={dd[0.9]:+.4%}")

    print(f"\nExclusions (across all looks): {exclude_totals}")
    print(f"Up-regime weeks in dev window: {up_regime_weeks:.2f} "
          "(trades/up-week is labeled an unconstrained upper bound, decision 9)")
    print(f"CSV written: {CSV_OUT} ({len(rows_for_csv)} rows)")


if __name__ == "__main__":
    main()
