#!/usr/bin/env python3
"""Look-ahead-safe rolling backtest (spec §4 note, §9 gate 1).

For each calendar month in the tested range: the whitelist is the top-N pairs
by the PREVIOUS month's quote volume (computed from downloaded candles), then
that month alone is backtested with a static pairlist. Results are aggregated
and checked against the spec gate: >=5 trades/week and positive profit at
taker fees. Usage: python3 scripts/rolling_backtest.py 2026-02 2026-07
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

TOP_N = 30
FEE = 0.004
# Mirrors the live VolumePairList min_value so the backtest universe can never
# include a pair the live pairlist would reject as too thin (critique 2026-07-19).
MIN_DAILY_QUOTE_VOLUME = 250_000
CANDLES_PER_DAY = 96  # 15m timeframe
DATA_DIR = Path("user_data/data/kraken")
RESULTS_DIR = Path("user_data/backtest_results")


def rank_pairs_for_month(data_dir: Path, month_start: pd.Timestamp, top_n: int) -> list[str]:
    prev_start = month_start - pd.offsets.MonthBegin(1)
    volumes = {}
    for f in sorted(Path(data_dir).glob("*-15m.feather")):
        df = pd.read_feather(f)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        prior = df[(df["date"] >= prev_start) & (df["date"] < month_start)]
        if len(prior) < 500:  # needs most of a month of prior candles
            continue
        qv = float((prior["close"] * prior["volume"]).sum())
        if qv / (len(prior) / CANDLES_PER_DAY) < MIN_DAILY_QUOTE_VOLUME:
            continue
        pair = f.stem.replace("-15m", "").replace("_", "/")
        volumes[pair] = qv
    return [p for p, _ in sorted(volumes.items(), key=lambda kv: -kv[1])[:top_n]]


def run_month(month_start: pd.Timestamp, pairs: list[str]) -> dict | None:
    month_end = month_start + pd.offsets.MonthBegin(1)
    timerange = f"{month_start:%Y%m%d}-{month_end:%Y%m%d}"
    cfg = json.loads(Path("config-paper.json").read_text())
    cfg["exchange"]["pair_whitelist"] = pairs
    cfg["pairlists"] = [{"method": "StaticPairList"}]
    Path("user_data/tmp_bt_config.json").write_text(json.dumps(cfg))
    out = subprocess.run(
        ["docker", "compose", "run", "--rm", "freqtrade", "backtesting",
         "--config", "/freqtrade/user_data/tmp_bt_config.json",
         "--strategy", "MemeMomentum", "--timerange", timerange,
         "--fee", str(FEE), "--enable-protections", "--export", "trades"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print(f"  {month_start:%Y-%m}: backtest FAILED\n{out.stderr[-2000:]}")
        return None
    # freqtrade writes a .last_result.json pointer to the newest result zip/json
    last = json.loads((RESULTS_DIR / ".last_result.json").read_text())
    result_file = RESULTS_DIR / last["latest_backtest"]
    stats = _load_stats(result_file)["strategy"]["MemeMomentum"]
    return {
        "month": f"{month_start:%Y-%m}",
        "trades": stats["total_trades"],
        "profit_pct": stats["profit_total"] * 100,
        "max_drawdown_pct": stats.get("max_drawdown_account", 0) * 100,
    }


def _load_stats(result_file: Path) -> dict:
    if result_file.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(result_file) as z:
            name = [n for n in z.namelist() if n.endswith(".json") and "config" not in n][0]
            return json.loads(z.read(name))
    return json.loads(result_file.read_text())


def main():
    start, end = pd.Timestamp(sys.argv[1], tz="UTC"), pd.Timestamp(sys.argv[2], tz="UTC")
    months, results = pd.date_range(start, end, freq="MS", tz="UTC"), []
    for m in months:
        pairs = rank_pairs_for_month(DATA_DIR, m, TOP_N)
        if not pairs:
            print(f"  {m:%Y-%m}: no rankable pairs (missing prior-month data), skipped")
            continue
        print(f"  {m:%Y-%m}: backtesting {len(pairs)} pairs...")
        r = run_month(m, pairs)
        if r:
            results.append(r)
    weeks = max(len(results) * 4.345, 1)
    total_trades = sum(r["trades"] for r in results)
    summary = {
        "months": [r["month"] for r in results],
        "total_trades": total_trades,
        "trades_per_week": round(total_trades / weeks, 2),
        "total_profit_pct": round(sum(r["profit_pct"] for r in results), 2),
        "max_drawdown_pct": round(max((r["max_drawdown_pct"] for r in results), default=0), 2),
        "per_month": results,
    }
    summary["gate_pass"] = bool(
        summary["trades_per_week"] >= 5 and summary["total_profit_pct"] > 0
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "rolling_summary.json").write_text(json.dumps(summary, indent=2))
    lines = ["# Rolling backtest summary", "",
             f"Gate (>=5 trades/wk AND profit>0 at fee {FEE}): "
             f"{'PASS' if summary['gate_pass'] else 'FAIL'}", "",
             f"- Trades/week: {summary['trades_per_week']}",
             f"- Total profit: {summary['total_profit_pct']}%",
             f"- Worst monthly drawdown: {summary['max_drawdown_pct']}%", "",
             "| Month | Trades | Profit % | Max DD % |", "|---|---|---|---|"]
    lines += [f"| {r['month']} | {r['trades']} | {r['profit_pct']:.2f} | "
              f"{r['max_drawdown_pct']:.2f} |" for r in results]
    (RESULTS_DIR / "rolling_summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
