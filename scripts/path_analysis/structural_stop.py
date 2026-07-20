#!/usr/bin/env python3
"""The one exit lever family A never actually tested: the STRUCTURAL stop.

replay_family_a.py swept the pre-registered exit grid and called the exit lever
spent. That sweep had a hole. Spec s3's stop knob is
`{-4% fixed, structural = signal-bar range low, capped at -5%}` and the sweep
substituted a FLAT -5% for the structural leg. Those are close to opposites:

  flat -5%     is LOOSER than the -4% baseline on every trade.
  structural   is TIGHTER than -4% on most of them -- median coil width is
               ~3.5% and entries land just above range_high, so range_low sits
               around -3.5%, and the -5% cap binds only on the widest coils.

So the grid tested the baseline and something looser, and never tested the
tighter, structure-aware stop. That matters here because the path diagnostic
found the exact asymmetry a structural stop is built to exploit:

  winners barely dip   -- median drawdown before the 24h peak is -0.71%
                          (-0.80% among >=+4% movers), and only 9% of movers
                          touch -4% before peaking;
  losers pay full      -- avg loss -4.86%, i.e. essentially the whole stop.

A stop just under the coil should therefore cut losers sooner while rarely
touching winners. If that still does not close the ~0.85pp gap to breakeven,
"the exit lever is spent" is earned rather than assumed.

Same validated engine, same mechanic (a hard stop until the trailing stop
ratchets past it), only the per-trade LEVEL changes -- so this sits inside the
0.083%/trade validation envelope rather than outside it like the stagnation
cells did.

Usage: .venv/bin/python3 scripts/path_analysis/structural_stop.py
"""
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from replay_family_a import (ARM_FEES, ROI_SHAPES, load_dev_trades,  # noqa: E402
                             ratio_for_price, simulate, window_for)
from verify_breakout_cap import candles as signal_candles  # noqa: E402

STRUCT_CAP = -0.05      # spec s3: structural stop is capped at -5%


def structural_stops(trades: pd.DataFrame) -> pd.Series:
    """Per-trade absolute stop price = max(signal-bar range_low, entry x 0.95).

    Signal bar = open_date - 15m, the convention verify_breakout_cap.py and
    verify_regime_gating.py both validated. range_low is shift(1)-lagged in
    add_indicators, so it excludes the firing candle -- no look-ahead.
    """
    out = {}
    for t in trades.itertuples():
        df = signal_candles(t.pair)
        ts = t.open_date - pd.Timedelta(minutes=15)
        floor = t.open_rate * (1 + STRUCT_CAP)
        if ts not in df.index or pd.isna(df.loc[ts, "range_low"]):
            out[t.Index] = float("nan")
            continue
        out[t.Index] = max(float(df.loc[ts, "range_low"]), floor)
    return pd.Series(out)


def score(trades, windows, stops, arm, roi, trailing, stop_pct=None):
    """Per-trade net for one exit config on one arm. stop_pct=None => structural."""
    nets = []
    sub = trades[trades.arm == arm]
    for t in sub.itertuples():
        abs_stop = stops[t.Index] if stop_pct is None else None
        if stop_pct is None and pd.isna(abs_stop):
            continue
        r = simulate(t.open_date, t.open_rate, windows[t.Index], ARM_FEES[arm],
                     roi, stop_pct if stop_pct is not None else 0.0, trailing,
                     stop_abs=abs_stop)
        if r is not None:
            nets.append(r[0])
    if not nets:
        return None
    s = pd.Series(nets)
    w = s > 0
    return {"n": len(s), "per_trade": s.mean(), "win": w.mean(),
            "avg_win": s[w].mean() if w.any() else 0.0,
            "avg_loss": s[~w].mean() if (~w).any() else 0.0}


def main() -> None:
    trades = load_dev_trades()
    windows = {}
    for t in trades.itertuples():
        w, _ = window_for(t.pair, t.open_date)
        windows[t.Index] = w
    stops = structural_stops(trades)

    # How tight is the structural stop, as a net ratio from entry?
    depth = pd.Series({
        i: ratio_for_price(trades.loc[i, "open_rate"], stops[i],
                           ARM_FEES[trades.loc[i, "arm"]])
        for i in trades.index if not pd.isna(stops[i])})
    n_missing = int(stops.isna().sum())
    n_capped = int((depth <= STRUCT_CAP).sum())

    print(f"Family A dev entries: {len(trades)} "
          f"(L={sum(trades.arm == 'L')}, D={sum(trades.arm == 'D')})")
    print(f"Structural stop resolved for {len(depth)}; {n_missing} had no "
          f"signal-bar range (excluded from the structural rows only).\n")
    print("Structural stop depth from entry (net of fees):")
    print("  " + "  ".join(f"p{int(q * 100)}={depth.quantile(q):+.2%}"
                           for q in (0.1, 0.25, 0.5, 0.75, 0.9)))
    print(f"  tighter than the -4% baseline on {(depth > -0.04).mean():.0%} of "
          f"trades; the -5% cap binds on {n_capped / len(depth):.0%}\n")

    for arm in ("L", "D"):
        print(f"--- arm {arm} " + "-" * 66)
        print(f"  {'exit config':<34} {'n':>5}  {'/trade':>7}  {'win%':>5}  "
              f"{'avgW':>7}  {'avgL':>7}")
        rows = []
        for roi_name, roi in ROI_SHAPES.items():
            for trailing in (False, True):
                for stop_label, stop_pct in (("stop -4%", -0.04),
                                             ("stop STRUCTURAL", None)):
                    st = score(trades, windows, stops, arm, roi, trailing,
                               stop_pct)
                    if st is None:
                        continue
                    label = (f"roi={roi_name} trail={'on' if trailing else 'off'} "
                             f"{stop_label}")
                    rows.append((st["per_trade"], label, st))
        for _, label, st in sorted(rows, reverse=True):
            mark = " <-" if "STRUCTURAL" in label else ""
            print(f"  {label:<34} {st['n']:5d}  {st['per_trade']:+7.2%}  "
                  f"{st['win']:5.0%}  {st['avg_win']:+7.2%}  "
                  f"{st['avg_loss']:+7.2%}{mark}")
        best = max(rows)
        print(f"  best: {best[1]}  {best[0]:+.2%}/trade\n")

    # --- stop-depth sweep: DIAGNOSTIC, outside the pre-registered grid ------
    # The structural stop turned out LOOSER than -4% on most trades, so it did
    # not actually test the tight-stop idea. This does, in full generality: if
    # no depth anywhere on this curve closes the gap, the stop lever is spent
    # as a matter of measurement rather than assumption. Spec s3 pre-registers
    # only {-4%, structural}; adopting anything else is a scope change for
    # Austin, and a depth picked off this curve is fitted to the dev window.
    print("--- stop-depth sweep (DIAGNOSTIC ONLY, not pre-registered) " + "-" * 18)
    print("  roi=wider, trailing off — the best in-grid shape on both arms.")
    print(f"  {'stop':<16} {'arm L /trade':>13}  {'win%':>5}   "
          f"{'arm D /trade':>13}  {'win%':>5}")
    for label, pct in (("-1.5%", -0.015), ("-2%", -0.02), ("-2.5%", -0.025),
                       ("-3%", -0.03), ("-4% (baseline)", -0.04), ("-5%", -0.05),
                       ("-6%", -0.06), ("-8%", -0.08), ("none", -0.99)):
        cells = [score(trades, windows, stops, a, ROI_SHAPES["wider"], False, pct)
                 for a in ("L", "D")]
        print(f"  {label:<16} {cells[0]['per_trade']:>12.2%}  "
              f"{cells[0]['win']:5.0%}   {cells[1]['per_trade']:>12.2%}  "
              f"{cells[1]['win']:5.0%}")

    print("\nSlot contention ignored; in-sample on the dev window; the holdout "
          "seal truncates windows near 2025-08-31.")


if __name__ == "__main__":
    main()
