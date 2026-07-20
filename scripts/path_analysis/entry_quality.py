#!/usr/bin/env python3
"""Does any pre-registered ENTRY knob have headroom? (family A, dev window)

replay_family_a.py established that the exit lever is spent: all 24 variants of
the pre-registered exit grid lose money, the best single config across both
arms (ROI wider / trailing off / stop -4%) still runs about -0.94%/trade, and
the whole grid spans only ~0.4pp against a ~0.9pp gap to breakeven. That leaves
entry selectivity as the only remaining lever inside the spec.

The cheap way to test it: TIGHTENING a filter keeps a SUBSET of the entries we
already took, and we already have every one of those trades' real forward path.
So the effect of `range_max_width=0.04` or `volume_mult=3.0` can be measured
directly off the recorded population — no backtest, no iteration spent.

  Measurable: tightening (0.06 -> 0.04, 2.0x -> 3.0x, 1.5% -> 1.0%).
  NOT measurable: loosening (0.08, 1.5x, 2.0%) admits trades we never took,
  and `range_lookback` {32, 96} changes the range itself rather than filtering
  it. Those need a real run; they are reported as UNTESTABLE, not as null.

Each bucket is scored on the same validated engine and the same single exit
config for both arms (per spec s4 -- per-arm parameter forks would be a scope
change needing Austin).

Two honest limits on every number below:
  - Slot contention is ignored. Dropping trades frees slots the real harness
    might refill, and holding longer would compete for them. Occupancy was
    1.1-1.3 of 10 slots at baseline, so this is small, but it is not zero.
  - In-sample on the dev window, and a filter chosen off this table is more
    fitted than a blind grid pick.

Usage: .venv/bin/python3 scripts/path_analysis/entry_quality.py
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from replay_family_a import (ARM_FEES, ROI_SHAPES, load_dev_trades,  # noqa: E402
                             simulate, window_for)
from verify_breakout_cap import candles as signal_candles  # noqa: E402

# Best single cross-arm config from replay_family_a.py section 4.
EXIT_ROI, EXIT_STOP, EXIT_TRAIL = ROI_SHAPES["wider"], -0.04, False

# Pre-registered candidate values that TIGHTEN the current default (spec s3).
TIGHTENINGS = {
    "range_max_width <= 0.04": lambda d: d.range_width <= 0.04,
    "volume_mult >= 3.0":      lambda d: d.vol_ratio >= 3.0,
    "max_extension <= 0.010":  lambda d: d.extension <= 0.010,
}
UNTESTABLE = ["range_lookback 32 / 96 (changes the range, not a filter)",
              "range_max_width 0.08, volume_mult 1.5, max_extension 0.02 "
              "(loosening admits entries never taken)"]


def signal_features(trades: pd.DataFrame) -> pd.DataFrame:
    """Signal-bar range width, volume multiple and breakout extension.

    Signal bar = open_date - 15m (market fills land on the next candle -- the
    convention verify_breakout_cap.py and verify_regime_gating.py both use).
    Indicators come from that module's gap-filled loader so the 48-bar window
    spans 12 clock-hours exactly, matching freqtrade.
    """
    width, vol_ratio, ext = [], [], []
    for t in trades.itertuples():
        df = signal_candles(t.pair)
        ts = t.open_date - pd.Timedelta(minutes=15)
        if ts not in df.index:
            width.append(float("nan")); vol_ratio.append(float("nan"))
            ext.append(float("nan")); continue
        row = df.loc[ts]
        width.append(row["range_width"])
        vol_ratio.append(row["volume"] / row["vol_avg"] if row["vol_avg"] else float("nan"))
        ext.append(row["close"] / row["range_high"] - 1 if row["range_high"] else float("nan"))
    out = trades.copy()
    out["range_width"], out["vol_ratio"], out["extension"] = width, vol_ratio, ext
    return out


def score(sub: pd.DataFrame, windows: dict) -> dict:
    """Per-trade net under the fixed best-in-grid exit, both arms pooled."""
    nets = []
    for t in sub.itertuples():
        r = simulate(t.open_date, t.open_rate, windows[t.Index],
                     ARM_FEES[t.arm], EXIT_ROI, EXIT_STOP, EXIT_TRAIL)
        if r is not None:
            nets.append(r[0])
    if not nets:
        return {}
    s = pd.Series(nets)
    w = s > 0
    return {"n": len(s), "per_trade": s.mean(), "win": w.mean(),
            "avg_win": s[w].mean() if w.any() else 0.0,
            "avg_loss": s[~w].mean() if (~w).any() else 0.0}


def row(label: str, st: dict, base_n: int, peak: float) -> str:
    if not st:
        return f"  {label:<28} (no trades)"
    return (f"  {label:<28} {st['n']:5d} ({st['n'] / base_n:5.1%})  "
            f"{st['per_trade']:+7.2%}  {st['win']:5.0%}  {st['avg_win']:+7.2%}  "
            f"{st['avg_loss']:+7.2%}  {peak:+7.2%}")


def main() -> None:
    trades = signal_features(load_dev_trades())
    windows = {}
    for t in trades.itertuples():
        w, _ = window_for(t.pair, t.open_date)
        windows[t.Index] = w
    # 24h gross peak, for the "did the filter pick better coils?" column
    peaks = []
    for t in trades.itertuples():
        w = windows[t.Index].loc[:t.open_date + pd.Timedelta(hours=24)]
        peaks.append(w.high.max() / t.open_rate - 1 if len(w) else float("nan"))
    trades["peak24"] = peaks

    print(f"Family A dev entries: {len(trades)} "
          f"(L={sum(trades.arm == 'L')}, D={sum(trades.arm == 'D')})")
    print(f"Exit held fixed at the best cross-arm in-grid config: "
          f"ROI wider, trailing off, stop {EXIT_STOP:.0%}.\n")

    print("Signal-bar feature spread (what the defaults actually admitted):")
    for col, lab in (("range_width", "range width"),
                     ("vol_ratio", "volume / 48-bar mean"),
                     ("extension", "close above range high")):
        s = trades[col].dropna()
        print(f"  {lab:<24} " + "  ".join(
            f"p{int(q * 100)}={s.quantile(q):.3f}" for q in (0.1, 0.25, 0.5, 0.75, 0.9)))

    base = score(trades, windows)
    print(f"\n  {'filter':<28} {'trades':>5} {'kept':>8}  {'/trade':>7}  "
          f"{'win%':>5}  {'avgW':>7}  {'avgL':>7}  {'24h peak':>7}")
    print("  " + "-" * 84)
    print(row("(none — current defaults)", base, len(trades),
              trades.peak24.mean()))
    for label, mask_fn in TIGHTENINGS.items():
        m = mask_fn(trades).fillna(False)
        print(row(label, score(trades[m], windows), len(trades),
                  trades.loc[m, "peak24"].mean()))

    # the strictest combination of all three, as an upper bound on filtering
    combo = pd.Series(True, index=trades.index)
    for mask_fn in TIGHTENINGS.values():
        combo &= mask_fn(trades).fillna(False)
    print(row("ALL THREE at once", score(trades[combo], windows), len(trades),
              trades.loc[combo, "peak24"].mean()))

    print("\nNot testable this way (need a real run if pursued):")
    for u in UNTESTABLE:
        print(f"  - {u}")
    print("\nSlot contention ignored; in-sample on the dev window.")


if __name__ == "__main__":
    main()
