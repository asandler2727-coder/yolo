"""Convert Kraken's bulk OHLCVT CSV export into freqtrade's per-pair feather format.
Source: https://support.kraken.com/articles/360047124832 (all-pairs, all-history bulk
download) — CSVs are named "<ALTNAME>_<MINUTES>.csv" with columns
time(unix s),open,high,low,close,volume,trades and no header row.

Kraken's own pair codes (altname) don't always match freqtrade's normalized pair
names (e.g. Kraken's BTC ticker is "XBT", Dogecoin is "XDG"), so pairs are matched
via Kraken's public AssetPairs API rather than guessed.
"""
import json
import sys
import urllib.request
from pathlib import Path

import pandas as pd

SOURCE_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "master_q4"
TARGET_DIR = Path("user_data/data/kraken")
PAIRS_FILE = Path("user_data/pairs_usd.json")
TF_MINUTES = 15
TF_NAME = "15m"

BASE_ALIAS = {"BTC": "XBT", "DOGE": "XDG"}

with urllib.request.urlopen("https://api.kraken.com/0/public/AssetPairs", timeout=30) as r:
    asset_pairs = json.load(r)["result"]

wsname_to_altname = {
    v["wsname"]: v["altname"] for v in asset_pairs.values() if "wsname" in v
}

pairs = json.loads(PAIRS_FILE.read_text())
TARGET_DIR.mkdir(parents=True, exist_ok=True)

converted, missing_altname, missing_csv = [], [], []

for pair in pairs:
    base, quote = pair.split("/")
    kraken_base = BASE_ALIAS.get(base, base)
    altname = wsname_to_altname.get(f"{kraken_base}/{quote}") or wsname_to_altname.get(f"{base}/{quote}")
    if not altname:
        missing_altname.append(pair)
        continue

    csv_path = SOURCE_DIR / f"{altname}_{TF_MINUTES}.csv"
    if not csv_path.exists():
        missing_csv.append(pair)
        continue

    df = pd.read_csv(
        csv_path,
        header=None,
        names=["time", "open", "high", "low", "close", "volume", "trades"],
    )
    df["date"] = pd.to_datetime(df["time"], unit="s", utc=True).astype("datetime64[ms, UTC]")
    df = df[["date", "open", "high", "low", "close", "volume"]].sort_values("date")

    out_path = TARGET_DIR / f"{base}_{quote}-{TF_NAME}.feather"
    if out_path.exists():
        existing = pd.read_feather(out_path)
        df = pd.concat([existing, df]).drop_duplicates(subset="date", keep="last").sort_values("date")
    df.reset_index(drop=True).to_feather(out_path)
    converted.append((pair, len(df)))

print(f"Converted: {len(converted)}/{len(pairs)} pairs")
if missing_altname:
    print(f"No Kraken pair match for {len(missing_altname)}: {missing_altname}")
if missing_csv:
    print(f"No {TF_NAME} CSV found for {len(missing_csv)}: {missing_csv}")
