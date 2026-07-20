#!/usr/bin/env python3
"""Assert b' fills really sit ~2% below their placement-candle price.

Catches the freqtrade custom_price_max_distance_ratio clamp (b' spec s6.1):
with the knob left at its 0.02 default the limit can be silently repriced, so
every fill is checked by exact arithmetic instead of trusting the config.

A genuine b' fill satisfies one of:
  limit-fill: open_rate == 0.98 * (open of some candle within the 4h timeout
              window before the fill)  [limit placed at that candle's open]
  gap-fill:   open_rate == the open of a window candle that gapped below an
              earlier candle's limit   [freqtrade fills at the better open]
Anything else is UNEXPLAINED -> clamp/mechanics suspicion, listed explicitly.

Usage: verify_fill_depth.py result1.zip [result2.zip ...]
"""
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

DATA = Path("user_data/data/kraken")
DEPTH = 0.02
TIMEOUT_CANDLES = 16  # 4h of 15m candles
# Freqtrade rounds the limit to the pair's price precision (tick), so an exact
# 0.98*open match needs slack of about a tick. 5e-4 relative covers ticks up to
# ~5bp of price while staying 40x below the 2% depth being asserted.
RTOL = 5e-4

_cache: dict[str, pd.DataFrame] = {}


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        _cache[pair] = df.set_index("date").sort_index()
    return _cache[pair]


def trades_from_zip(zp: str) -> list[dict]:
    with zipfile.ZipFile(zp) as z:
        inner = [n for n in z.namelist() if n.endswith(".json")
                 and not n.endswith("_config.json")
                 and not n.endswith(".meta.json")]
        return json.loads(z.read(inner[0]))["strategy"]["MemeMomentum"]["trades"]


def classify(trade: dict) -> tuple[str, float]:
    """Return (kind, discount_vs_placement_open) for one fill."""
    open_date = pd.Timestamp(trade["open_date"])
    fill_rate = trade["open_rate"]
    df = candles(trade["pair"])
    window = df.loc[open_date - pd.Timedelta(minutes=15 * TIMEOUT_CANDLES):
                    open_date]
    opens = window["open"]
    limit_hits = opens[abs(opens * (1 - DEPTH) - fill_rate)
                       <= RTOL * fill_rate]
    if len(limit_hits):
        return "limit-fill", 1 - fill_rate / limit_hits.iloc[-1]
    gap_hits = opens[abs(opens - fill_rate) <= RTOL * fill_rate]
    if len(gap_hits):
        # Filled at a candle open that gapped under an earlier candle's limit.
        earlier = opens.loc[:gap_hits.index[0]].iloc[:-1]
        if len(earlier) and (earlier * (1 - DEPTH) > fill_rate).any():
            ref = earlier[earlier * (1 - DEPTH) > fill_rate].iloc[-1]
            return "gap-fill", 1 - fill_rate / ref
    return "UNEXPLAINED", float("nan")


def main():
    rows = []
    for zp in sys.argv[1:]:
        for t in trades_from_zip(zp):
            kind, disc = classify(t)
            rows.append({"pair": t["pair"], "open_date": t["open_date"],
                         "open_rate": t["open_rate"], "kind": kind,
                         "discount": disc})
    d = pd.DataFrame(rows)
    if d.empty:
        print("No trades in the given results.")
        return
    counts = d["kind"].value_counts()
    print(f"{len(d)} fills: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    ok = d[d["kind"] != "UNEXPLAINED"]
    if len(ok):
        print(f"discount vs placement-candle open: median "
              f"{ok['discount'].median():+.2%}  max {ok['discount'].max():+.2%}")
    bad = d[d["kind"] == "UNEXPLAINED"]
    if len(bad):
        print("\nUNEXPLAINED fills (clamp/mechanics suspicion):")
        print(bad.to_string(index=False))
        sys.exit(1)
    print("All fills consistent with a 2% resting limit -> no clamping.")


if __name__ == "__main__":
    main()
