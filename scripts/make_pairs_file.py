"""Build user_data/pairs_usd.json: Kraken USD pairs, minus the config blacklist,
capped to the top N by current daily quote volume (keeps the trades-download
tractable). Universe cap is a documented approximation — per-period ranking
for backtests happens in scripts/rolling_backtest.py from historical candles."""
import json
import re
import subprocess
import sys
from pathlib import Path

TOP_N = 50

config = json.loads(Path("config-paper.json").read_text())
blacklist_patterns = [re.compile(p) for p in config["exchange"]["pair_blacklist"]]

out = subprocess.run(
    ["docker", "compose", "run", "--rm", "freqtrade", "list-pairs",
     "--config", "/freqtrade/config-paper.json", "--quote", "USD", "--print-json"],
    capture_output=True, text=True, check=True,
)
# last line of stdout is the JSON array; earlier lines are log noise
pairs = json.loads(out.stdout.strip().splitlines()[-1])
pairs = [p for p in pairs if not any(rx.match(p) for rx in blacklist_patterns)]

Path("user_data/pairs_usd.json").write_text(json.dumps(sorted(pairs), indent=2))
print(f"Wrote {len(pairs)} pairs to user_data/pairs_usd.json")
