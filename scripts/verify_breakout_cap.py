#!/usr/bin/env python3
"""Assert every family-A fill obeyed BOTH anti-chase bounds (spec s3/s7):
  signal bound: the signal candle closed above range_high and inside the cap
  fill bound:   open_rate <= the SIGNAL bar's frozen cap
The signal bar = open_date - 15m (market fills land on the next candle; same
convention verify_regime_gating.py validated on 36/83/90 trades). range_high
is recomputed from the pair's candles with the strategy's own add_indicators,
so this is an independent re-derivation, not a readback.

Tick tolerance: RTOL relative slack (same rationale as verify_fill_depth.py —
freqtrade rounds prices to the pair's tick, b' XCN false-alarm lesson).

Candle gaps: freqtrade fills missing 15m candles (ohlcv_fill_up_missing_data,
default on) with prev-close flat bars at volume 0, so its 48-bar range spans
exactly 12 clock-hours. The re-derivation must do the same or its window
reaches further back across gaps and picks up older highs (found on the
2024-11 smoke: 5 false SIGNAL-NOT-BREAKOUT flags, all on gapped pairs).

Usage: verify_breakout_cap.py result1.zip [result2.zip ...]
Exit 1 on any violation.
"""
import json
import sys
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import DEFAULT_PARAMS, add_indicators  # noqa: E402

DATA = Path("user_data/data/kraken")
RTOL = 5e-4

_cache: dict[str, pd.DataFrame] = {}


def fill_missing_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Mirror freqtrade's ohlcv_fill_up_missing_data: reindex onto the full
    15m grid; filler candles are flat at the previous close with volume 0."""
    df = df.set_index("date").sort_index()
    full = df.resample("15min").asfreq()
    close = full["close"].ffill()
    for col in ("open", "high", "low"):
        full[col] = full[col].fillna(close)
    full["close"] = close
    full["volume"] = full["volume"].fillna(0.0)
    return full.reset_index()


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = fill_missing_candles(df)
        _cache[pair] = add_indicators(df, DEFAULT_PARAMS).set_index("date")
    return _cache[pair]


def trades_from_zip(zp: str) -> list[dict]:
    with zipfile.ZipFile(zp) as z:
        inner = [n for n in z.namelist() if n.endswith(".json")
                 and not n.endswith("_config.json")
                 and not n.endswith(".meta.json")]
        return json.loads(z.read(inner[0]))["strategy"]["MemeMomentum"]["trades"]


def check(trade: dict) -> tuple[str, float]:
    """Return (verdict, fill/cap ratio). OK = both bounds hold."""
    open_date = pd.Timestamp(trade["open_date"])
    df = candles(trade["pair"])
    signal_time = open_date - pd.Timedelta(minutes=15)
    if signal_time not in df.index:
        return "NO-SIGNAL-BAR", float("nan")
    row = df.loc[signal_time]
    if pd.isna(row["range_high"]):
        return "NO-RANGE", float("nan")
    cap = row["range_high"] * (1 + DEFAULT_PARAMS["max_extension"])
    ratio = trade["open_rate"] / cap
    if row["close"] <= row["range_high"] * (1 - RTOL):
        return "SIGNAL-NOT-BREAKOUT", ratio
    if row["close"] > cap * (1 + RTOL):
        return "SIGNAL-ABOVE-CAP", ratio
    if trade["open_rate"] > cap * (1 + RTOL):
        return "FILL-ABOVE-CAP", ratio
    return "OK", ratio


def main():
    rows = []
    for zp in sys.argv[1:]:
        for t in trades_from_zip(zp):
            verdict, ratio = check(t)
            rows.append({"pair": t["pair"], "open_date": t["open_date"],
                         "open_rate": t["open_rate"], "verdict": verdict,
                         "fill_over_cap": ratio})
    d = pd.DataFrame(rows)
    if d.empty:
        print("No trades in the given results.")
        return
    counts = d["verdict"].value_counts()
    print(f"{len(d)} fills: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    ok = d[d["verdict"] == "OK"]
    if len(ok):
        print(f"fill/cap ratio: median {ok['fill_over_cap'].median():.4f}  "
              f"max {ok['fill_over_cap'].max():.4f}")
    bad = d[d["verdict"] != "OK"]
    if len(bad):
        print("\nVIOLATIONS:")
        print(bad.to_string(index=False))
        sys.exit(1)
    print("All fills obey the signal-bar-frozen anti-chase cap (both bounds).")


if __name__ == "__main__":
    main()
