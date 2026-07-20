"""Survey how deep the Kraken USD universe is, month by month, back through 2024.

Two questions this answers before the family-A (range breakout) spec can pin its
windows and its down-cap arm:
  1. Universe depth: how many pairs clear given avg-daily-quote-volume floors each
     month (liquid arm needs >=30 above $250k/day; down-cap arm needs a real
     population in the rank-31..100 band).
  2. BTC regime mix: % of 1h bars in the v2 up-regime (close>EMA50 & EMA20>EMA50)
     per month, so development/holdout windows are judgeable for an
     up-regime-gated strategy.

Survey only — final arm membership always comes from rank_pairs_for_month in
scripts/rolling_backtest.py, the single source of truth for ranking.
"""
import glob
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

DATA = "user_data/data/kraken"
START, END = "2023-12-01", "2026-07-16"


def universe_depth() -> None:
    rows = []
    for f in sorted(glob.glob(f"{DATA}/*_USD-15m.feather")):
        pair = f.split("/")[-1].replace("_USD-15m.feather", "")
        df = pd.read_feather(f, columns=["date", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df[(df["date"] >= START) & (df["date"] < END)]
        if df.empty:
            continue
        month = df["date"].dt.to_period("M")
        quote = (df["close"] * df["volume"]).groupby(month).sum()
        days = df["date"].dt.normalize().groupby(month).nunique()
        for m, adv in (quote / days).items():
            rows.append((str(m), pair, adv))

    t = pd.DataFrame(rows, columns=["month", "pair", "adv"])
    out = []
    for m, g in t.groupby("month"):
        g = g.sort_values("adv", ascending=False).reset_index(drop=True)
        band = g.iloc[30:100]  # rank 31..100 by volume
        out.append((
            m, len(g),
            int((g["adv"] >= 250_000).sum()),
            int((g["adv"] >= 100_000).sum()),
            int((g["adv"] >= 50_000).sum()),
            int((band["adv"] >= 100_000).sum()),
            int((band["adv"] >= 50_000).sum()),
        ))
    res = pd.DataFrame(out, columns=[
        "month", "pairs", ">=250k", ">=100k", ">=50k",
        "r31-100>=100k", "r31-100>=50k"])
    print("=== UNIVERSE DEPTH (avg daily quote volume, USD pairs) ===")
    print(res.to_string(index=False))


def regime_mix() -> None:
    btc = pd.read_feather(f"{DATA}/BTC_USD-15m.feather", columns=["date", "close"])
    btc["date"] = pd.to_datetime(btc["date"], utc=True)
    btc = btc[btc["date"] >= "2023-06-01"].set_index("date")
    h = btc["close"].resample("1h").last().dropna()
    ema20 = h.ewm(span=20, adjust=False).mean()
    ema50 = h.ewm(span=50, adjust=False).mean()
    reg = ((h > ema50) & (ema20 > ema50)).loc["2024-01-01":]
    mix = (reg.groupby(reg.index.to_period("M")).mean() * 100).round(1)
    print("\n=== BTC UP-REGIME % OF 1H BARS PER MONTH (v2 rule) ===")
    print(mix.to_string())


if __name__ == "__main__":
    universe_depth()
    regime_mix()
