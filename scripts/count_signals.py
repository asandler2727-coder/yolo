#!/usr/bin/env python3
"""Count v2 entry-signal candles per month over the ranked-30 universe.

Denominator for the b' fill-rate diagnostic: b' places a resting limit per
signal, so fills/signals measures how many signals the 2%-deeper entry missed.
Reuses the harness's own ranking and the regime-audit script's reconstruction
of freqtrade's informative-merge offset, so the mask here is the one the
strategy actually trades.

Usage: count_signals.py 2026-02 2026-07   (inclusive month range)
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
sys.path.insert(0, str(Path(__file__).parent))
from momentum_signals import DEFAULT_PARAMS, add_indicators, entry_mask  # noqa: E402
from rolling_backtest import DATA_DIR, TOP_N, rank_pairs_for_month  # noqa: E402
from verify_regime_gating import regime_lookup_series  # noqa: E402

WARMUP = pd.Timedelta(days=3)  # covers EMA50 + vol48 + impulse windows


def month_signals(month_start: pd.Timestamp, lut: pd.DataFrame) -> tuple[int, int]:
    month_end = month_start + pd.offsets.MonthBegin(1)
    pairs = rank_pairs_for_month(DATA_DIR, month_start, TOP_N)
    total = 0
    for pair in pairs:
        f = Path(DATA_DIR) / f"{pair.replace('/', '_')}-15m.feather"
        if not f.exists():
            continue
        df = pd.read_feather(f)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df[(df["date"] >= month_start - WARMUP) & (df["date"] < month_end)]
        if len(df) < 100:
            continue
        df = add_indicators(df.reset_index(drop=True), DEFAULT_PARAMS)
        # Regime available to candle with open time T: newest 1h bucket whose
        # availability time (bucket_open + 45m, per the informative merge)
        # is <= T. Same lookup the regime audit validated against real trades.
        left = df[["date"]].copy()
        left["date"] = left["date"].astype("datetime64[us, UTC]")
        right = lut.rename(columns={"avail": "date"}).copy()
        right["date"] = right["date"].astype("datetime64[us, UTC]")
        merged = pd.merge_asof(left, right, on="date", direction="backward")
        regime = pd.Series(
            merged["regime_ok"].fillna(False).astype(bool).values, index=df.index)
        mask = entry_mask(df, DEFAULT_PARAMS, regime)
        total += int((mask & (df["date"] >= month_start)).sum())
    return total, len(pairs)


def main():
    start = pd.Timestamp(sys.argv[1], tz="UTC")
    end = pd.Timestamp(sys.argv[2], tz="UTC")
    lut = regime_lookup_series()
    month = start
    print("month    pairs  signal_candles")
    while month <= end:
        n, npairs = month_signals(month, lut)
        print(f"{month:%Y-%m}   {npairs:3d}   {n:6d}")
        month += pd.offsets.MonthBegin(1)


if __name__ == "__main__":
    main()
