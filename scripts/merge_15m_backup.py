#!/usr/bin/env python3
"""Restore Jan-Mar candles after freqtrade's trades->OHLCV conversion.

freqtrade's `convert_trades_to_ohlcv` OVERWRITES each pair's 15m feather with
candles built only from the stored trades (verified against the 2026.4 source:
`ohlcv_store(data=ohlcv)`, no merge). Most gap-pair trades files start
2026-04-01, so the conversion wipes the Jan-Mar candles that came from the
official Kraken bulk OHLCVT export. This script merges the pre-conversion
backup back in: for every pair, union(backup, current) deduped on candle date,
with the CURRENT (trades-derived) row winning any overlap.

Usage: python3 scripts/merge_15m_backup.py [backup_dir] [live_dir]
Defaults: user_data/data/kraken_15m_backup_20260720 -> user_data/data/kraken
"""
import sys
from pathlib import Path

import pandas as pd

COLS = ["date", "open", "high", "low", "close", "volume"]


def merge_pair(backup_file: Path, live_file: Path) -> tuple[int, int, int]:
    """Merge one pair; returns (backup_rows, live_rows_before, rows_after)."""
    old = pd.read_feather(backup_file)
    old["date"] = pd.to_datetime(old["date"], utc=True)
    if live_file.exists():
        new = pd.read_feather(live_file)
        new["date"] = pd.to_datetime(new["date"], utc=True)
    else:
        # Conversion skipped this pair (e.g. no trades in range) - keep backup.
        new = old.iloc[0:0]
    merged = (
        pd.concat([old[COLS], new[COLS]])
        .drop_duplicates(subset="date", keep="last")
        .sort_values("date")
        .reset_index(drop=True)
    )
    merged.to_feather(live_file)
    return len(old), len(new), len(merged)


def main():
    backup_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        "user_data/data/kraken_15m_backup_20260720")
    live_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("user_data/data/kraken")
    backups = sorted(backup_dir.glob("*-15m.feather"))
    if not backups:
        sys.exit(f"No backup feathers found in {backup_dir}")
    grew, unchanged = 0, 0
    for bf in backups:
        n_old, n_new, n_merged = merge_pair(bf, live_dir / bf.name)
        if n_merged > max(n_old, n_new):
            grew += 1
        else:
            unchanged += 1
    print(f"Merged {len(backups)} pairs: {grew} gained history, {unchanged} unchanged.")
    for probe in ["BTC_USD", "ETH_USD", "SOL_USD", "XLM_USD", "AAVE_USD"]:
        f = live_dir / f"{probe}-15m.feather"
        if f.exists():
            df = pd.read_feather(f)
            d = pd.to_datetime(df["date"], utc=True)
            dupes = int(d.duplicated().sum())
            print(f"  {probe}: {d.min():%Y-%m-%d %H:%M} -> {d.max():%Y-%m-%d %H:%M} "
                  f"({len(df)} rows, {dupes} duplicate dates)")


if __name__ == "__main__":
    main()
