#!/usr/bin/env python3
"""Task 6 one-parameter-at-a-time sweep (plan step 2). Edits the two strategy
files in place, runs the rolling backtest per variation, appends each row to
user_data/backtest_results/sweep_results.jsonl, and always restores the
originals when done. Usage: .venv/bin/python scripts/param_sweep.py 2026-02 2026-03
"""
import json
import re
import subprocess
import sys
from pathlib import Path

SIGNALS = Path("user_data/strategies/momentum_signals.py")
STRATEGY = Path("user_data/strategies/MemeMomentum.py")
RESULTS = Path("user_data/backtest_results/sweep_results.jsonl")
SUMMARY = Path("user_data/backtest_results/rolling_summary.json")

# (label, file, regex, replacement-template, values) — baseline values excluded,
# they're already recorded from the baseline run.
SWEEP = [
    ("momentum_threshold", SIGNALS,
     r'"momentum_threshold": [0-9.]+', '"momentum_threshold": {v}', [0.02, 0.04, 0.05]),
    ("volume_mult", SIGNALS,
     r'"volume_mult": [0-9.]+', '"volume_mult": {v}', [1.5, 3.0]),
    ("stoploss", STRATEGY,
     r"stoploss = -[0-9.]+", "stoploss = {v}", [-0.05, -0.08]),
    ("roi_0", STRATEGY,
     r'minimal_roi = \{"0": [0-9.]+', 'minimal_roi = {{"0": {v}', [0.06, 0.15]),
]


def run_one(label, value, start, end):
    r = subprocess.run(
        [".venv/bin/python", "scripts/rolling_backtest.py", start, end],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        row = {"param": label, "value": value, "error": r.stderr[-500:]}
    else:
        s = json.loads(SUMMARY.read_text())
        row = {"param": label, "value": value,
               "trades_per_week": s["trades_per_week"],
               "total_profit_pct": s["total_profit_pct"],
               "max_drawdown_pct": s["max_drawdown_pct"],
               "gate_pass": s["gate_pass"]}
    with RESULTS.open("a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)


def main():
    start, end = sys.argv[1], sys.argv[2]
    originals = {p: p.read_text() for p in (SIGNALS, STRATEGY)}
    try:
        for label, path, pattern, template, values in SWEEP:
            for v in values:
                for p, text in originals.items():  # each run varies ONE param
                    p.write_text(text)
                new = re.sub(pattern, template.format(v=v), originals[path])
                assert new != originals[path], f"pattern failed: {label}"
                path.write_text(new)
                run_one(label, v, start, end)
    finally:
        for p, text in originals.items():
            p.write_text(text)
        print("originals restored", flush=True)


if __name__ == "__main__":
    main()
