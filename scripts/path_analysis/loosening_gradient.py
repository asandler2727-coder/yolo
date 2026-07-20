#!/usr/bin/env python3
"""Can the three untested LOOSENING cells plausibly rescue family A?

Spec s3 pre-registers three cells no run has tested and entry_quality.py could
not score (loosening admits trades never taken): range_max_width 0.08,
volume_mult 1.5, max_extension 0.02. The tightening sweep found every
tightening WORSE, which reads as a gradient pointing loose-ward. This script
measures that gradient where we can see it -- INSIDE the recorded population,
bucketed by each filter feature up to its current boundary -- so the
extrapolation past the boundary is bounded by data instead of argued.

Two facts frame the readout:
 1. Loosening KEEPS every current trade. Arm L's core is 843 trades at
    -0.90%/trade, so a loosened cell passes the gate only if the newly
    admitted trades are profitable enough to outweigh that core:
    E_new > 0.90% * (843 / N_new) on arm L. The table prints this bar next
    to the observed within-population gradient.
 2. The marginal band nearest each boundary is the best available estimate
    of what lies just past it. Quality declines with looseness by design,
    so the band average is, if anything, an optimistic bound.

Same validated engine, same fixed exit (ROI wider / trailing off / stop -4%)
as entry_quality.py. Reads recorded dev trades only; the holdout seal in
window_for() applies as everywhere else.

Usage: .venv/bin/python3 scripts/path_analysis/loosening_gradient.py
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from entry_quality import signal_features  # noqa: E402
from replay_family_a import (ARM_FEES, ROI_SHAPES, load_dev_trades,  # noqa: E402
                             simulate, window_for)

EXIT_ROI, EXIT_STOP, EXIT_TRAIL = ROI_SHAPES["wider"], -0.04, False

BUCKETS = {
    "range_width": [(0.00, 0.02), (0.02, 0.03), (0.03, 0.045), (0.045, 0.061)],
    "vol_ratio":   [(2.0, 2.5), (2.5, 3.0), (3.0, 5.0), (5.0, float("inf"))],
    "extension":   [(0.000, 0.003), (0.003, 0.006), (0.006, 0.010),
                    (0.010, 0.0151)],
}
# the loosened cell each feature's boundary band extrapolates toward
LOOSENED = {"range_width": "range_max_width 0.06 -> 0.08",
            "vol_ratio": "volume_mult 2.0 -> 1.5",
            "extension": "max_extension 0.015 -> 0.02"}


def net_per_trade(sub: pd.DataFrame, windows: dict) -> tuple[int, float]:
    nets = []
    for t in sub.itertuples():
        r = simulate(t.open_date, t.open_rate, windows[t.Index],
                     ARM_FEES[t.arm], EXIT_ROI, EXIT_STOP, EXIT_TRAIL)
        if r is not None:
            nets.append(r[0])
    return len(nets), (sum(nets) / len(nets) if nets else float("nan"))


def main() -> None:
    trades = signal_features(load_dev_trades())
    windows = {t.Index: window_for(t.pair, t.open_date)[0]
               for t in trades.itertuples()}

    n_all, e_all = net_per_trade(trades, windows)
    print(f"Family A dev entries: {n_all} scored; population expectancy "
          f"{e_all:+.2%}/trade (exit: ROI wider, trail off, stop -4%).\n")

    for col, bands in BUCKETS.items():
        print(f"--- {col} (loosening target: {LOOSENED[col]}) " + "-" * 20)
        print(f"  {'band':<22} {'n':>5}  {'/trade':>8}")
        for lo, hi in bands:
            m = (trades[col] >= lo) & (trades[col] < hi)
            n, e = net_per_trade(trades[m], windows)
            hi_lab = "inf" if hi == float("inf") else f"{hi:.3f}"
            print(f"  [{lo:.3f}, {hi_lab:<6})      {n:>5}  {e:>+8.2%}")
        print()

    print("What a loosened cell would need to PASS the gate (arm L):")
    core_n, core_e = 843, -0.0090
    for frac in (0.10, 0.25, 0.50, 1.00):
        n_new = int(core_n * frac)
        need = -core_e * core_n / n_new
        print(f"  admit +{frac:.0%} more trades ({n_new:4d}): newly admitted "
              f"trades must average {need:+.2%}/trade just to reach zero")
    print("\nEvery number in-sample on the dev window; slot contention "
          "ignored; seal truncation as in replay_family_a.py.")


if __name__ == "__main__":
    main()
