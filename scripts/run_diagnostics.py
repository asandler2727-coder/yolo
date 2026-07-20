#!/usr/bin/env python3
"""Per-run family-A diagnostics (spec s3: hold/slot reporting is mandatory in
dev — Austin's stagnation-off amendment made these the cost meter for parked
slots; the fill-veto count is an auditor pin).

For each result zip (with the .log rolling_backtest saved next to it):
  - ENTRY-VETO / STAKE-SKIP counts from the captured strategy log
  - per-trade stats: win rate, avg win/loss/trade, exit-reason breakdown
  - hold-time distribution: median / p90 / max hours
  - slot occupancy: mean/max concurrent trades, fraction of span at capacity
  - up-regime trades/week over the pooled window (v2 amended-gate divisor)
Ends with a ready-to-paste DEV markdown row for docs/backtests.md.

Usage: run_diagnostics.py result1.zip [result2.zip ...]
"""
import json
import re
import sys
import warnings
import zipfile
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import (  # noqa: E402
    DEFAULT_PARAMS, regime_mask_from_btc, resample_1h,
)

BTC = Path("user_data/data/kraken/BTC_USD-15m.feather")
MAX_SLOTS = 10


def count_vetoes(log_text: str) -> int:
    return len(re.findall(r"ENTRY-VETO pair=", log_text))


def count_stake_skips(log_text: str) -> int:
    return len(re.findall(r"STAKE-SKIP pair=", log_text))


def slot_occupancy(trades: list[dict], max_slots: int = MAX_SLOTS) -> dict:
    """Time-weighted concurrency from open/close timestamps (event sweep)."""
    if not trades:
        return {"mean_concurrent": 0.0, "max_concurrent": 0, "frac_time_full": 0.0}
    events = []
    for t in trades:
        events.append((pd.Timestamp(t["open_date"]), 1))
        events.append((pd.Timestamp(t["close_date"]), -1))
    events.sort(key=lambda e: (e[0], -e[1]))
    span = (events[-1][0] - events[0][0]).total_seconds()
    if span <= 0:
        return {"mean_concurrent": float(len(trades)), "max_concurrent": len(trades),
                "frac_time_full": 1.0 if len(trades) >= max_slots else 0.0}
    level, prev_t = 0, events[0][0]
    weighted, full_time, max_level = 0.0, 0.0, 0
    for ts, delta in events:
        dt = (ts - prev_t).total_seconds()
        weighted += level * dt
        if level >= max_slots:
            full_time += dt
        level += delta
        max_level = max(max_level, level)
        prev_t = ts
    return {"mean_concurrent": weighted / span, "max_concurrent": max_level,
            "frac_time_full": full_time / span}


def hold_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"median_h": 0.0, "p90_h": 0.0, "max_h": 0.0}
    d = pd.Series([t["trade_duration"] for t in trades]) / 60.0
    return {"median_h": float(d.median()), "p90_h": float(d.quantile(0.9)),
            "max_h": float(d.max())}


def trades_from_zip(zp: str) -> list[dict]:
    with zipfile.ZipFile(zp) as z:
        inner = [n for n in z.namelist() if n.endswith(".json")
                 and not n.endswith("_config.json")
                 and not n.endswith(".meta.json")]
        return json.loads(z.read(inner[0]))["strategy"]["MemeMomentum"]["trades"]


def up_regime_weeks(start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Weeks of BTC up-regime time inside [start, end) — the v2 amended-gate
    frequency divisor."""
    btc = pd.read_feather(BTC, columns=["date", "close"])
    btc["date"] = pd.to_datetime(btc["date"], utc=True)
    h = resample_1h(btc)
    h["up"] = regime_mask_from_btc(h, DEFAULT_PARAMS)
    win = h[(h["date"] >= start) & (h["date"] < end)]
    return float(win["up"].sum()) / (24 * 7)


def main():
    all_trades, veto_total, skip_total = [], 0, 0
    for zp in sys.argv[1:]:
        all_trades.extend(trades_from_zip(zp))
        log = Path(zp).with_suffix(".log")
        if log.exists():
            text = log.read_text()
            veto_total += count_vetoes(text)
            skip_total += count_stake_skips(text)
        else:
            print(f"WARNING: no log next to {zp} — veto count incomplete")
    n = len(all_trades)
    print(f"{n} trades across {len(sys.argv) - 1} result file(s)")
    print(f"ENTRY-VETO: {veto_total}   STAKE-SKIP: {skip_total}")
    if not n:
        return
    p = pd.Series([t["profit_ratio"] for t in all_trades]) * 100
    wins = p[p > 0]
    losses = p[p <= 0]
    print(f"win rate {len(wins)}/{n} ({100 * len(wins) / n:.0f}%)  "
          f"avg win {wins.mean():+.2f}%  avg loss {losses.mean():+.2f}%  "
          f"avg trade {p.mean():+.2f}%")
    reasons = pd.Series([t["exit_reason"] for t in all_trades]).value_counts()
    print("exits: " + ", ".join(f"{k}={v}" for k, v in reasons.items()))
    hs = hold_stats(all_trades)
    print(f"hold: median {hs['median_h']:.1f}h  p90 {hs['p90_h']:.1f}h  "
          f"max {hs['max_h']:.1f}h")
    occ = slot_occupancy(all_trades)
    print(f"slots: mean {occ['mean_concurrent']:.2f}  max {occ['max_concurrent']}"
          f"  at-capacity {occ['frac_time_full']:.1%} of span")
    opens = pd.to_datetime(pd.Series([t["open_date"] for t in all_trades]), utc=True)
    start = opens.min().floor("D")
    end = opens.max().ceil("D")
    upw = up_regime_weeks(start, end)
    tpw = n / upw if upw > 0 else float("inf")
    print(f"up-regime weeks in span: {upw:.1f} -> {tpw:.1f} trades/up-week")
    print("\nDEV row (fill Iter/Knob/Hypothesis/Arm/Profit/DD from the run summary):")
    print(f"| ? | {pd.Timestamp.utcnow():%Y-%m-%d} | ? | ? | ? | {n} | ?% | ?% | "
          f"{tpw:.1f} | {veto_total} | {hs['median_h']:.1f} | "
          f"{occ['max_concurrent']} | |")


if __name__ == "__main__":
    main()
