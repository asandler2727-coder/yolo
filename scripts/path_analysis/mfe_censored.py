#!/usr/bin/env python3
"""Feasibility check for the v2.1 exit redesign (option b).

Reads the six recorded v2 rolling-backtest result zips (Feb-Jul 2026) and asks:
how far past entry did each trade's price actually run (MFE = max_rate/open-1)?
If winners rarely ran past the +3% ROI cap, uncapped exits cannot help and the
redesign is dead before coding. Also computes an UPPER-BOUND simulation of a
peak-ratchet exit (arm at +A%, exit when price falls T% off the peak) using the
intrabar peak — real close-based exits would capture less.

All of Feb-Jul is in-sample for any design informed by this analysis.

AUDIT NOTE (2026-07-20): both conclusions this script suggests are wrong on their own.
The MFE table is censored at exit time (a +3% ROI exit hides the coin's later path), and
the "upper-bound" simulation feeds that censored max_rate into the trail math, so it is
not an upper bound at all. Kept only as a record of the censoring lesson; the audited
evidence is replay_uncensored.py / final_replay.py plus the independent review in
docs/exit-path-analysis-2026-07-20.md section 8.
"""
import json
import zipfile
from pathlib import Path

import pandas as pd

BASE = Path("user_data/backtest_results")
ZIPS = {
    "2026-02": "backtest-result-2026-07-19_07-59-26.zip",
    "2026-03": "backtest-result-2026-07-19_07-59-33.zip",
    "2026-04": "backtest-result-2026-07-20_05-26-27.zip",
    "2026-05": "backtest-result-2026-07-20_05-26-35.zip",
    "2026-06": "backtest-result-2026-07-20_05-26-41.zip",
    "2026-07": "backtest-result-2026-07-20_05-26-48.zip",
}
ROUND_TRIP_FEE = 0.008  # 0.4% taker each side


def load_trades() -> pd.DataFrame:
    rows = []
    for month, name in ZIPS.items():
        with zipfile.ZipFile(BASE / name) as z:
            inner = [n for n in z.namelist()
                     if n.endswith(".json") and not n.endswith("_config.json")
                     and not n.endswith(".meta.json")]
            assert len(inner) == 1, (name, inner)
            data = json.loads(z.read(inner[0]))
        trades = data["strategy"]["MemeMomentum"]["trades"]
        for t in trades:
            rows.append({
                "month": month,
                "pair": t["pair"],
                "open_date": t["open_date"],
                "duration_min": t["trade_duration"],
                "open_rate": t["open_rate"],
                "close_rate": t["close_rate"],
                "max_rate": t.get("max_rate"),
                "min_rate": t.get("min_rate"),
                "profit_ratio": t["profit_ratio"],   # net of fees
                "exit_reason": t["exit_reason"],
            })
    return pd.DataFrame(rows)


def main():
    df = load_trades()
    df["mfe"] = df.max_rate / df.open_rate - 1.0   # intrabar peak vs entry
    df["mae"] = df.min_rate / df.open_rate - 1.0

    n = len(df)
    wins = df[df.profit_ratio > 0]
    losses = df[df.profit_ratio <= 0]
    print(f"trades={n}  win_rate={len(wins)/n:.1%}  "
          f"avg_win={wins.profit_ratio.mean():+.2%}  "
          f"avg_loss={losses.profit_ratio.mean():+.2%}  "
          f"total_sum_ratio={df.profit_ratio.sum():+.2%}")
    print("\nexit reasons (count, mean net profit, mean MFE, mean duration h):")
    g = df.groupby("exit_reason").agg(
        n=("profit_ratio", "size"),
        mean_profit=("profit_ratio", "mean"),
        mean_mfe=("mfe", "mean"),
        mean_dur_h=("duration_min", lambda s: s.mean() / 60),
    )
    print(g.to_string(float_format=lambda x: f"{x:+.3f}"))

    print("\nMFE distribution (share of ALL trades whose peak reached X):")
    for x in [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.20]:
        share = (df.mfe >= x).mean()
        cnt = int((df.mfe >= x).sum())
        print(f"  peak >= {x:>4.0%}: {cnt:3d} trades ({share:.1%})")

    print("\nMFE deciles:")
    print(df.mfe.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 1.0])
          .to_string(float_format=lambda x: f"{x:+.3%}"))

    # Tail mass: sum of (MFE - 3%) over trades with MFE > 3% -- the profit the
    # ROI cap threw away, before any trail give-back.
    tail = (df.mfe[df.mfe > 0.03] - 0.03).sum()
    print(f"\nProfit surrendered above the 3% cap (sum of MFE-3% where MFE>3%): "
          f"{tail:+.1%} across {(df.mfe > 0.03).sum()} trades")

    # Upper-bound ratchet simulation. Rule per trade:
    #   peak < arm  -> original outcome unchanged
    #   peak >= arm -> exit at peak*(1-trail), net of round-trip fee
    # Uses intrabar peak and ignores slot contention -> OPTIMISTIC bound.
    print("\nUpper-bound ratchet simulation (net of 0.8% fees; OPTIMISTIC):")
    print("  arm   trail | total_net  win%  avg_win  avg_loss  vs_actual")
    actual_total = df.profit_ratio.sum()
    for arm in [0.015, 0.02]:
        for trail in [0.02, 0.025, 0.03, 0.04]:
            armed = df.mfe >= arm
            sim_exit_gross = df.mfe * 0.0  # placeholder series
            sim = df.profit_ratio.copy()
            sim[armed] = (1 + df.mfe[armed]) * (1 - trail) - 1 - ROUND_TRIP_FEE
            total = sim.sum()
            w = sim > 0
            print(f"  {arm:.1%}  {trail:.1%} | {total:+8.1%}  {w.mean():.0%}  "
                  f"{sim[w].mean():+.2%}  {sim[~w].mean():+.2%}   "
                  f"({total - actual_total:+.1%})")

    print("\nPer-month actual totals (sum of profit_ratio):")
    print(df.groupby("month").profit_ratio.agg(["size", "sum"])
          .to_string(float_format=lambda x: f"{x:+.3f}"))


if __name__ == "__main__":
    main()
