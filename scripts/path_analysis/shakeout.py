#!/usr/bin/env python3
"""Pre-peak shakeout measurement for the 119 recorded v2 trades.

For each trade, find the 24h-window peak (highest high), then measure:
- time-to-peak (hours from entry)
- MAE-before-peak: lowest low between entry and the peak candle, vs entry
  (how deep the shakeout ran BEFORE the move paid)
- whether the -4% stop would have fired before the peak

This diagnoses WHERE the money is lost: if typical MAE-before-peak is -2..-4%,
the entry is buying before the shakeout completes, and no exit rule downstream
can fix that. Diagnostic only -- no parameter search.
"""
import json
import zipfile
from pathlib import Path

import pandas as pd

BASE = Path("user_data/backtest_results")
DATA = Path("user_data/data/kraken")
ZIPS = {
    "2026-02": "backtest-result-2026-07-19_07-59-26.zip",
    "2026-03": "backtest-result-2026-07-19_07-59-33.zip",
    "2026-04": "backtest-result-2026-07-20_05-26-27.zip",
    "2026-05": "backtest-result-2026-07-20_05-26-35.zip",
    "2026-06": "backtest-result-2026-07-20_05-26-41.zip",
    "2026-07": "backtest-result-2026-07-20_05-26-48.zip",
}

_cache: dict[str, pd.DataFrame] = {}


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        _cache[pair] = df.set_index("date").sort_index()
    return _cache[pair]


def load_trades() -> pd.DataFrame:
    rows = []
    for month, name in ZIPS.items():
        with zipfile.ZipFile(BASE / name) as z:
            inner = [n for n in z.namelist()
                     if n.endswith(".json") and not n.endswith("_config.json")
                     and not n.endswith(".meta.json")]
            data = json.loads(z.read(inner[0]))
        for t in data["strategy"]["MemeMomentum"]["trades"]:
            rows.append({"month": month, "pair": t["pair"],
                         "open_date": pd.Timestamp(t["open_date"]),
                         "open_rate": t["open_rate"]})
    return pd.DataFrame(rows)


def main():
    trades = load_trades()
    recs = []
    for t in trades.itertuples():
        w = candles(t.pair).loc[t.open_date: t.open_date + pd.Timedelta(hours=24)]
        if len(w) == 0:
            continue
        peak_ts = w.high.idxmax()
        peak = w.high.max() / t.open_rate - 1
        before = w.loc[:peak_ts]                      # entry..peak inclusive
        mae_before = before.low.min() / t.open_rate - 1
        recs.append({
            "peak24": peak,
            "hours_to_peak": (peak_ts - t.open_date).total_seconds() / 3600,
            "mae_before_peak": mae_before,
            "stopped_before_peak": mae_before <= -0.04,
        })
    df = pd.DataFrame(recs)
    n = len(df)

    print(f"{n} trades\n")
    print("Time to 24h peak (hours):")
    print(df.hours_to_peak.quantile([0.25, 0.5, 0.75, 0.9])
          .to_string(float_format=lambda x: f"{x:.1f}"))
    print(f"  share of peaks arriving after 6h (stagnation horizon): "
          f"{(df.hours_to_peak > 6).mean():.1%}")

    print("\nMAE before the peak (lowest point between entry and peak):")
    print(df.mae_before_peak.quantile([0.1, 0.25, 0.5, 0.75, 0.9])
          .to_string(float_format=lambda x: f"{x:+.2%}"))
    for x in (-0.01, -0.02, -0.03, -0.04):
        print(f"  dipped below {x:+.0%} before peaking: "
              f"{(df.mae_before_peak <= x).sum():3d} ({(df.mae_before_peak <= x).mean():.1%})")
    print(f"\n-4% stop fired BEFORE the peak: {df.stopped_before_peak.sum()} "
          f"({df.stopped_before_peak.mean():.1%})")

    # The joint question: among trades with a real move (peak >= 4%), how deep
    # was the pre-peak shakeout? This is the money-losing mechanism if deep.
    movers = df[df.peak24 >= 0.04]
    print(f"\nAmong the {len(movers)} trades whose 24h peak reached >= 4%:")
    print("  MAE before peak: "
          + "  ".join(f"p{int(q*100)}={movers.mae_before_peak.quantile(q):+.2%}"
                      for q in (0.25, 0.5, 0.75)))
    print(f"  peak arrived after 6h: {(movers.hours_to_peak > 6).mean():.1%}")
    print(f"  stop fired before peak: {movers.stopped_before_peak.mean():.1%}")


if __name__ == "__main__":
    main()
