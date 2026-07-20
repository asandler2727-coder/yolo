#!/usr/bin/env python3
"""Uncensored path replay for the 119 recorded v2 trades (Feb-Jul 2026).

The trade records' max_rate is censored at exit time (a +3% ROI exit after 3h
hides whatever the coin did afterwards). This replays each trade's candles from
entry for up to 48h, ignoring the old exits, to get:

1. The UNCENSORED peak distribution at 24h / 48h -- the ceiling for ANY exit
   system on these entries.
2. A perfect-exit ceiling: sell the exact 48h top, minus fees.
3. An honest close-based ratchet replay (arm A, trail T off the peak close,
   hard stop -4% intrabar, 6h stagnation <1%, 48h time cap), candle by candle,
   stop checked before trail within a candle (conservative ordering).

All in-sample by declaration; this informs the (b) go/no-go, not a tuned run.
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
FEE = 0.008          # round trip taker
STOP = -0.04
STAG_H, STAG_LVL = 6, 0.01
CAP_H = 48

_cache: dict[str, pd.DataFrame] = {}


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        f = DATA / f"{pair.replace('/', '_')}-15m.feather"
        df = pd.read_feather(f)
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
                         "open_rate": t["open_rate"],
                         "actual_profit": t["profit_ratio"]})
    return pd.DataFrame(rows)


def replay(trade, arm: float, trail: float):
    """Close-based ratchet replay. Returns (net_profit, exit_tag, hold_h)."""
    df = candles(trade.pair)
    entry = trade.open_rate
    window = df.loc[trade.open_date: trade.open_date + pd.Timedelta(hours=CAP_H)]
    if len(window) == 0:
        return None
    peak_close = -1.0
    armed = False
    for i, (ts, row) in enumerate(window.iterrows()):
        hours = (ts - trade.open_date).total_seconds() / 3600
        # 1) hard stop, intrabar, checked first (conservative ordering)
        if row.low / entry - 1 <= STOP:
            return STOP - FEE, "stop", hours
        # 2) ratchet on closes
        peak_close = max(peak_close, row.close)
        if not armed and peak_close / entry - 1 >= arm:
            armed = True
        if armed and row.close <= peak_close * (1 - trail):
            return row.close / entry - 1 - FEE, "ratchet", hours
        # 3) stagnation (mirrors current rule)
        if hours >= STAG_H and row.close / entry - 1 < STAG_LVL and not armed:
            return row.close / entry - 1 - FEE, "stagnation", hours
    last = window.iloc[-1]
    return last.close / entry - 1 - FEE, "time_cap", hours


def uncensored_peaks(trade):
    df = candles(trade.pair)
    out = {}
    for h in (24, 48):
        w = df.loc[trade.open_date: trade.open_date + pd.Timedelta(hours=h)]
        out[h] = (w.high.max() / trade.open_rate - 1) if len(w) else float("nan")
    return out


def main():
    trades = load_trades()
    print(f"replaying {len(trades)} trades against candle data...")

    peaks24, peaks48 = [], []
    for t in trades.itertuples():
        p = uncensored_peaks(t)
        peaks24.append(p[24])
        peaks48.append(p[48])
    trades["peak24"] = peaks24
    trades["peak48"] = peaks48

    for col, label in [("peak24", "24h"), ("peak48", "48h")]:
        s = trades[col].dropna()
        print(f"\nUNCENSORED peak within {label} of entry ({len(s)} trades):")
        print("  deciles: " + "  ".join(
            f"p{int(q*100)}={s.quantile(q):+.1%}"
            for q in (0.25, 0.5, 0.75, 0.9, 0.95, 1.0)))
        for x in (0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.15, 0.20):
            print(f"    peak >= {x:>4.0%}: {(s >= x).sum():3d} ({(s >= x).mean():.1%})")

    ceiling48 = (trades.peak48 - FEE).sum()
    ceiling24 = (trades.peak24 - FEE).sum()
    actual = trades.actual_profit.sum()
    print(f"\nPerfect-exit ceiling (sell the exact top, minus fees):")
    print(f"  24h: {ceiling24:+.1%} sum ({ceiling24/len(trades):+.2%}/trade)")
    print(f"  48h: {ceiling48:+.1%} sum ({ceiling48/len(trades):+.2%}/trade)")
    print(f"  actual v2:      {actual:+.1%} sum ({actual/len(trades):+.2%}/trade)")

    print("\nClose-based ratchet replay (stop first, 6h stagnation, 48h cap):")
    print("  arm   trail | total_net   /trade  win%  avg_win  avg_loss  exits(stop/ratchet/stag/cap)")
    for arm, trail in [(0.015, 0.02), (0.02, 0.02), (0.02, 0.025),
                       (0.02, 0.03), (0.03, 0.03)]:
        res = [replay(t, arm, trail) for t in trades.itertuples()]
        res = [r for r in res if r is not None]
        s = pd.DataFrame(res, columns=["net", "tag", "hold_h"])
        w = s.net > 0
        tags = s.tag.value_counts()
        print(f"  {arm:.1%}  {trail:.1%} | {s.net.sum():+8.1%}  {s.net.mean():+.2%}  "
              f"{w.mean():.0%}  {s.net[w].mean() if w.any() else 0:+.2%}  "
              f"{s.net[~w].mean():+.2%}   "
              f"{tags.get('stop',0)}/{tags.get('ratchet',0)}/"
              f"{tags.get('stagnation',0)}/{tags.get('time_cap',0)}")


if __name__ == "__main__":
    main()
