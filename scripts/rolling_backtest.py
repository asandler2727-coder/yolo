#!/usr/bin/env python3
"""Look-ahead-safe rolling backtest with two universe arms (family A spec §4).

For each calendar month in the tested range: the whitelist comes from the
PREVIOUS month's quote volume (computed from downloaded candles), then that
month alone is backtested with a static pairlist. Arm L = $250k/day floor
then top-30 (the live VolumePairList mirror). Arm D = rank the FULL USD set,
slice rank positions 31..100, THEN drop under $100k/day. Fees per arm are the
spec's pre-registered taker+slippage handicaps.
Usage: python3 scripts/rolling_backtest.py 2024-02 2025-08 --arm L
"""
import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import pandas as pd

TOP_N = 30
# Arm L mirrors the live VolumePairList min_value: floor first, then top-N.
MIN_DAILY_QUOTE_VOLUME = 250_000
# Arm D (family A spec s4, auditor pin): rank the FULL USD set by prior-month
# quote volume, slice rank positions 31..100, THEN drop under $100k/day —
# the reverse order of arm L, so sub-floor pairs still occupy rank slots.
DOWNCAP_BAND = (30, 100)
DOWNCAP_MIN_DAILY_QUOTE_VOLUME = 100_000
# Per-arm backtest fee = taker + slippage handicap (spec s4, pre-registered).
ARM_FEES = {"L": 0.0045, "D": 0.006}
CANDLES_PER_DAY = 96  # 15m timeframe
DATA_DIR = Path("user_data/data/kraken")
RESULTS_DIR = Path("user_data/backtest_results")


def _prior_month_volumes(data_dir: Path, month_start: pd.Timestamp) -> dict:
    """pair -> (total quote volume, avg daily quote volume) for the month
    before `month_start`. Under 500 prior candles = unrankable, skipped."""
    prev_start = month_start - pd.offsets.MonthBegin(1)
    out = {}
    for f in sorted(Path(data_dir).glob("*-15m.feather")):
        df = pd.read_feather(f, columns=["date", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], utc=True)
        prior = df[(df["date"] >= prev_start) & (df["date"] < month_start)]
        if len(prior) < 500:
            continue
        qv = float((prior["close"] * prior["volume"]).sum())
        adv = qv / (len(prior) / CANDLES_PER_DAY)
        pair = f.stem.replace("-15m", "").replace("_", "/")
        out[pair] = (qv, adv)
    return out


def rank_pairs_for_month(data_dir: Path, month_start: pd.Timestamp, top_n: int) -> list[str]:
    """Arm L: drop pairs under the $250k/day floor, then take the top-N by
    prior-month quote volume (the live VolumePairList mirror, unchanged)."""
    vols = _prior_month_volumes(data_dir, month_start)
    eligible = {p: qv for p, (qv, adv) in vols.items()
                if adv >= MIN_DAILY_QUOTE_VOLUME}
    return [p for p, _ in sorted(eligible.items(), key=lambda kv: -kv[1])[:top_n]]


def rank_pairs_downcap_for_month(data_dir: Path, month_start: pd.Timestamp) -> list[str]:
    """Arm D: rank the FULL set, slice rank positions 31..100, THEN floor.
    Its own path per the auditor pin — never reuse arm L's floor-then-top-N."""
    vols = _prior_month_volumes(data_dir, month_start)
    ranked = sorted(vols.items(), key=lambda kv: -kv[1][0])
    band = ranked[DOWNCAP_BAND[0]:DOWNCAP_BAND[1]]
    return [p for p, (qv, adv) in band
            if adv >= DOWNCAP_MIN_DAILY_QUOTE_VOLUME]


def result_file_from_output(output: str, results_dir: Path) -> Path | None:
    """Locate the result THIS run wrote by parsing freqtrade's own stdout,
    which prints e.g. `dumping json to ".../backtest-result-<ts>.meta.json"`.

    Reading the shared `.last_result.json` pointer instead is unsafe: over a
    macOS Docker Desktop bind mount that host-side read can return a stale
    value from a *previous* run before the container's write propagates, which
    silently attributed old v1 numbers to a v2 run. The stdout is captured
    in-process, so it names this run's file with no filesystem race.
    """
    matches = re.findall(
        r'dumping json to "([^"]*backtest-result-[^"]*\.meta\.json)"', output
    )
    if not matches:
        return None
    return results_dir / Path(matches[-1]).name.replace(".meta.json", ".zip")


def run_month(month_start: pd.Timestamp, pairs: list[str], fee: float) -> dict | None:
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
         "--fee", str(fee), "--enable-protections", "--export", "trades"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print(f"  {month_start:%Y-%m}: backtest FAILED\n{out.stderr[-2000:]}")
        return None
    # Use the file THIS run reported, not the shared pointer (see docstring).
    result_file = result_file_from_output(out.stdout + out.stderr, RESULTS_DIR)
    if result_file is None:
        print(f"  {month_start:%Y-%m}: could not find result file in output")
        return None
    # The zip itself may lag the stdout line across the bind mount; wait briefly.
    for _ in range(20):
        if result_file.exists():
            break
        time.sleep(0.5)
    if not result_file.exists():
        print(f"  {month_start:%Y-%m}: result file {result_file.name} never appeared")
        return None
    # Keep this run's full output: the dev diagnostics count ENTRY-VETO /
    # STAKE-SKIP lines from it (strategy logger -> stdout).
    (RESULTS_DIR / (result_file.stem + ".log")).write_text(out.stdout + out.stderr)
    stats = _load_stats(result_file)["strategy"]["MemeMomentum"]
    row = {
        "month": f"{month_start:%Y-%m}",
        "trades": stats["total_trades"],
        "profit_pct": stats["profit_total"] * 100,
        "max_drawdown_pct": stats.get("max_drawdown_account", 0) * 100,
    }
    # Inline so a stale/mismatched read is visible in the run log, not silent.
    print(f"  {row['month']}: {result_file.name} -> "
          f"{row['trades']} trades, {row['profit_pct']:.2f}% profit")
    return row


def _load_stats(result_file: Path) -> dict:
    if result_file.suffix == ".zip":
        import zipfile
        with zipfile.ZipFile(result_file) as z:
            name = [n for n in z.namelist() if n.endswith(".json") and "config" not in n][0]
            return json.loads(z.read(name))
    return json.loads(result_file.read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("start")
    ap.add_argument("end")
    ap.add_argument("--arm", choices=["L", "D"], required=True,
                    help="L = top-30/$250k floor @ fee 0.0045; "
                         "D = rank 31-100/$100k floor @ fee 0.006")
    args = ap.parse_args()
    fee = ARM_FEES[args.arm]
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    months, results = pd.date_range(start, end, freq="MS", tz="UTC"), []
    for m in months:
        if args.arm == "L":
            pairs = rank_pairs_for_month(DATA_DIR, m, TOP_N)
        else:
            pairs = rank_pairs_downcap_for_month(DATA_DIR, m)
        if not pairs:
            print(f"  {m:%Y-%m}: no rankable pairs (missing prior-month data), skipped")
            continue
        print(f"  {m:%Y-%m} arm {args.arm}: backtesting {len(pairs)} pairs...")
        r = run_month(m, pairs, fee)
        if r:
            results.append(r)
    weeks = max(len(results) * 4.345, 1)
    total_trades = sum(r["trades"] for r in results)
    summary = {
        "arm": args.arm,
        "fee": fee,
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
    (RESULTS_DIR / f"rolling_summary_{args.arm}.json").write_text(
        json.dumps(summary, indent=2))
    lines = [f"# Rolling backtest summary — arm {args.arm} (fee {fee})", "",
             f"Gate (>=5 trades/wk AND profit>0 at fee {fee}): "
             f"{'PASS' if summary['gate_pass'] else 'FAIL'}", "",
             f"- Trades/week: {summary['trades_per_week']}",
             f"- Total profit: {summary['total_profit_pct']}%",
             f"- Worst monthly drawdown: {summary['max_drawdown_pct']}%", "",
             "| Month | Trades | Profit % | Max DD % |", "|---|---|---|---|"]
    lines += [f"| {r['month']} | {r['trades']} | {r['profit_pct']:.2f} | "
              f"{r['max_drawdown_pct']:.2f} |" for r in results]
    (RESULTS_DIR / f"rolling_summary_{args.arm}.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
