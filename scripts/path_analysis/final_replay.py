#!/usr/bin/env python3
"""FINAL replay batch: does fixing the TIME dimension rescue the exits?

The shakeout analysis showed 73% of real moves peak after the 6h stagnation
horizon (median time-to-peak ~14h among movers). This batch replays the same
119 trades with the stagnation rule relaxed to match the measured move
development time, on top of the uncapped ratchet:

  - hard stop -4% intrabar (unchanged, checked first in-candle)
  - arm at +2% peak close, trail T% off peak close
  - stagnation: exit at 24h if net-flat (<0% gross), instead of 6h <1%
  - hard time cap 72h

4 combos only (trail 3/4% x stagnation 24h/none). This is the last in-sample
look: if all negative, exits cannot harvest these entries, full stop.
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
FEE = 0.008
STOP = -0.04
ARM = 0.02
CAP_H = 72

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


def replay(trade, trail: float, stag_h):
    df = candles(trade.pair)
    entry = trade.open_rate
    w = df.loc[trade.open_date: trade.open_date + pd.Timedelta(hours=CAP_H)]
    if len(w) == 0:
        return None
    peak_close, armed = -1.0, False
    hours = 0.0
    for ts, row in w.iterrows():
        hours = (ts - trade.open_date).total_seconds() / 3600
        if row.low / entry - 1 <= STOP:
            return STOP - FEE, "stop", hours
        peak_close = max(peak_close, row.close)
        if not armed and peak_close / entry - 1 >= ARM:
            armed = True
        if armed and row.close <= peak_close * (1 - trail):
            return row.close / entry - 1 - FEE, "ratchet", hours
        if stag_h and hours >= stag_h and row.close / entry - 1 < 0 and not armed:
            return row.close / entry - 1 - FEE, "stagnation", hours
    last = w.iloc[-1]
    return last.close / entry - 1 - FEE, "time_cap", hours


def main():
    trades = load_trades()
    print(f"{len(trades)} trades; arm={ARM:.0%}, stop={STOP:.0%}, cap={CAP_H}h\n")
    print(" trail  stag | total_net   /trade  win%  avg_win  avg_loss  med_hold_h  exits(stop/ratchet/stag/cap)")
    for trail in (0.03, 0.04):
        for stag_h in (24, None):
            res = [r for t in trades.itertuples()
                   if (r := replay(t, trail, stag_h)) is not None]
            s = pd.DataFrame(res, columns=["net", "tag", "hold_h"])
            w = s.net > 0
            tags = s.tag.value_counts()
            per_month = None
            print(f"  {trail:.0%}   {str(stag_h or '-'):>4} | {s.net.sum():+8.1%}  "
                  f"{s.net.mean():+.2%}  {w.mean():.0%}  {s.net[w].mean():+.2%}  "
                  f"{s.net[~w].mean():+.2%}   {s.hold_h.median():5.1f}      "
                  f"{tags.get('stop',0)}/{tags.get('ratchet',0)}/"
                  f"{tags.get('stagnation',0)}/{tags.get('time_cap',0)}")

    # Month split for the best-performing variant is printed only if any total
    # is positive; otherwise the verdict is uniform and months don't matter.


if __name__ == "__main__":
    main()
