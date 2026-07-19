#!/usr/bin/env python3
"""Independent check that EVERY backtested trade opened while BTC was in the
up-regime — the signals pkl lacked enter_long, so this reconstructs the regime
the strategy actually gated on and audits it against real trade open times.

Regime is BTC-derived and pair-independent: resample 15m->1h, EMA trend, then
the SAME offset freqtrade's merge_informative_pair applies (date_merge =
bucket_open + timeframe_inf - timeframe = +1h -15m = +45m). A 15m signal candle
at time T therefore sees the newest 1h bucket with bucket_open + 45m <= T.
A trade fills on the candle after its signal, so the signal candle = open_date
- 15m. We assert regime True on that signal candle for every trade.
"""
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import DEFAULT_PARAMS, regime_mask_from_btc, resample_1h

BTC = Path("user_data/data/kraken/BTC_USD-15m.feather")
RESULTS = [Path(p) for p in sys.argv[1:]]


def load_trades(zip_path):
    with zipfile.ZipFile(zip_path) as z:
        name = [n for n in z.namelist() if n.endswith(".json") and "config" not in n][0]
        data = json.loads(z.read(name))
    return data["strategy"]["MemeMomentum"]["trades"]


def regime_lookup_series():
    btc = pd.read_feather(BTC)
    btc["date"] = pd.to_datetime(btc["date"], utc=True)
    btc_1h = resample_1h(btc)
    btc_1h["regime_ok"] = regime_mask_from_btc(btc_1h, DEFAULT_PARAMS)
    # Availability time of each 1h bucket to a 15m stream (freqtrade's offset).
    btc_1h["avail"] = btc_1h["date"] + pd.Timedelta(hours=1) - pd.Timedelta(minutes=15)
    return btc_1h[["avail", "regime_ok"]].sort_values("avail").reset_index(drop=True)


def main():
    lut = regime_lookup_series()
    rows = []
    for zp in RESULTS:
        for t in load_trades(zp):
            open_date = pd.Timestamp(t["open_date"]).tz_convert("UTC")
            signal_candle = open_date - pd.Timedelta(minutes=15)
            avail = lut[lut["avail"] <= signal_candle]
            regime = bool(avail["regime_ok"].iloc[-1]) if len(avail) else False
            rows.append({"pair": t["pair"], "open_date": open_date,
                         "regime_ok": regime, "profit_pct": t["profit_ratio"] * 100})
    df = pd.DataFrame(rows)
    total, up = len(df), int(df["regime_ok"].sum())
    print(f"Trades audited: {total}")
    print(f"Opened in UP-regime:   {up}")
    print(f"Opened in DOWN-regime: {total - up}")
    if total - up:
        print("\nLEAK — trades that opened out of up-regime:")
        print(df[~df["regime_ok"]].to_string(index=False))
    else:
        print("\nAll trades opened in up-regime -> gating is sound; the loss is "
              "genuine in-regime negative expectancy.")
    wins = (df["profit_pct"] > 0).sum()
    print(f"\nWin rate: {wins}/{total} ({100*wins/total:.0f}%)  "
          f"avg trade: {df['profit_pct'].mean():.2f}%")


if __name__ == "__main__":
    main()
