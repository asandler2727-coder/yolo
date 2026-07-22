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
from pathlib import Path

import numpy as np
import pandas as pd

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


_ENTRY_COLUMNS = ["signal_ts", "fill_ts", "fill", "fwd_ret", "month", "extension"]


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
    -> False (fail-closed, spec s4)."""
    idx_df = pd.DataFrame({"ts": index}).sort_values("ts")
    merged = pd.merge_asof(idx_df, lut.sort_values("avail"),
                           left_on="ts", right_on="avail", direction="backward")
    regime = merged["regime_ok"].fillna(False).astype(bool)
    return pd.Series(regime.to_numpy(), index=merged["ts"]).reindex(index).fillna(False)


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

    print(f"\nExclusions (across all looks): {exclude_totals}")
    print(f"Up-regime weeks in dev window: {up_regime_weeks:.2f} "
          "(trades/up-week is labeled an unconstrained upper bound, decision 9)")
    print(f"CSV written: {CSV_OUT} ({len(rows_for_csv)} rows)")


if __name__ == "__main__":
    main()
