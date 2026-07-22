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
