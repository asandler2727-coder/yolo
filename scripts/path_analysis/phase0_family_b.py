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
import numpy as np
import pandas as pd

# --- grids (spec s3, pre-registered) ----------------------------------------
REF_LOOKBACKS = (48, 96, 192)
MIN_EXTS = (0.005, 0.01, 0.02)
MAX_EXTS = (0.03, 0.04, 0.06)
VOL_MULTS = (1.5, 2.0, 3.0)
VOLUME_WINDOW = 96
HORIZON_BARS = {"24h": 96, "48h": 192, "96h": 384}

# --- holdout seal ------------------------------------------------------------
SEAL_TS = pd.Timestamp("2025-09-01", tz="UTC")
DEV_START = pd.Timestamp("2024-02-01", tz="UTC")


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
