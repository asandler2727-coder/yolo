# YOLO Meme Momentum Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Freqtrade bot that scans the whole Kraken USD market for trending high-volume coins and trades them with a 15m momentum strategy — paper first, live only after the gates in the spec pass.

**Architecture:** Freqtrade (Docker) is the engine; a dynamic pairlist (volume + movement + liquidity filters) picks what to watch; one strategy (`MemeMomentum`) built on a pure-pandas signal module makes entries; exits are stop-loss + trailing stop + stagnation timeout. A rolling backtest harness re-ranks the universe per month from historical volume so backtests can't peek at today's trending list.

**Tech Stack:** Freqtrade stable (Docker image `freqtradeorg/freqtrade:stable`), Python 3 + pandas + pytest for local tests, FreqUI for monitoring, Windows 11 + Docker Desktop for deployment.

**Spec:** `docs/superpowers/specs/2026-07-18-yolo-meme-momentum-bot-design.md` — read it first; its §6 guardrails and §8 security rules override anything here if they ever conflict.

## Global Constraints

- Every committed config has `"dry_run": true`. `config-live.json` is gitignored and never created by this plan (it's created manually at go-live, after Austin's explicit "I am ready to go live").
- Bankroll: `dry_run_wallet: 750`, `max_open_trades: 3`, `stake_amount: 250`. Never raise in any task.
- Protections (CooldownPeriod, StoplossGuard, MaxDrawdown) are defined in the strategy and never removed or weakened.
- No API keys anywhere in the repo, in any task, ever. Paper mode needs no keys (public data only).
- Acceptance gate (spec §5/§9): ≥5 trades/week average in backtest AND positive total profit at `--fee 0.004` (Kraken taker). A plan that ends below that bar goes back to Task 6 tuning, not to deployment.
- Backtest universe selection must use only data from *before* each tested period (no look-ahead).
- Local tests use only `pandas` + `pytest` (no freqtrade install needed on the Mac); anything needing freqtrade runs through Docker.
- Commit after every task (plain-English commit messages).

---

### Task 1: Freqtrade scaffolding + dynamic pairlist config

**Files:**
- Create: `docker-compose.yml`
- Create: `config-paper.json`
- Create: `user_data/strategies/.gitkeep`

**Interfaces:**
- Produces: `config-paper.json` (all later tasks build on it), a running `docker compose run --rm freqtrade ...` invocation pattern.

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  freqtrade:
    image: freqtradeorg/freqtrade:stable
    restart: unless-stopped
    container_name: yolo-freqtrade
    volumes:
      - "./user_data:/freqtrade/user_data"
      - "./config-paper.json:/freqtrade/config-paper.json:ro"
    ports:
      - "127.0.0.1:8080:8080"
    command: >
      trade
      --config /freqtrade/config-paper.json
      --strategy MemeMomentum
    environment:
      - FREQTRADE__API_SERVER__JWT_SECRET_KEY=${FT_JWT_SECRET:-dev-only-secret}
      - FREQTRADE__API_SERVER__PASSWORD=${FT_PASS:-yolo-dev}
```

- [ ] **Step 2: Write `config-paper.json`**

```json
{
    "bot_name": "YOLO",
    "strategy": "MemeMomentum",
    "timeframe": "15m",
    "dry_run": true,
    "dry_run_wallet": 750,
    "max_open_trades": 3,
    "stake_currency": "USD",
    "stake_amount": 250,
    "tradable_balance_ratio": 1.0,
    "fiat_display_currency": "USD",
    "trading_mode": "spot",
    "cancel_open_orders_on_exit": false,
    "unfilledtimeout": {"entry": 10, "exit": 10, "unit": "minutes"},
    "entry_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    },
    "exit_pricing": {
        "price_side": "same",
        "use_order_book": true,
        "order_book_top": 1
    },
    "exchange": {
        "name": "kraken",
        "key": "",
        "secret": "",
        "pair_whitelist": [],
        "pair_blacklist": [
            "^(USDT|USDC|DAI|PYUSD|USDS|USDG|RLUSD|TUSD|EURT|EURC|EURR|EUR|GBP|AUD|CHF|CAD|JPY|TBTC|WBTC|CBBTC|LSETH|WETH|WAXL)/.*"
        ]
    },
    "pairlists": [
        {
            "method": "VolumePairList",
            "number_assets": 30,
            "sort_key": "quoteVolume",
            "min_value": 250000,
            "refresh_period": 1800
        },
        {"method": "SpreadFilter", "max_spread_ratio": 0.005},
        {"method": "PriceFilter", "low_price_ratio": 0.005},
        {
            "method": "RangeStabilityFilter",
            "lookback_days": 1,
            "min_rate_of_change": 0.02,
            "refresh_period": 1800
        }
    ],
    "telegram": {"enabled": false, "token": "", "chat_id": ""},
    "api_server": {
        "enabled": true,
        "listen_ip_address": "0.0.0.0",
        "listen_port": 8080,
        "verbosity": "error",
        "jwt_secret_key": "SET_VIA_ENV",
        "CORS_origins": [],
        "username": "yolo",
        "password": "SET_VIA_ENV"
    },
    "initial_state": "running",
    "force_enter_enable": false,
    "internals": {"process_throttle_secs": 5}
}
```

Notes for the implementer: the pairlist chain is the spec's §4 — top 30 USD pairs by quote volume with ≥$250k/day, then drop wide spreads, precision-hostile prices, and anything that moved <2% in the last day. The regex blacklist kills stablecoins/pegged/wrapped assets and fiat. Austin's personal holdings must be added to `pair_blacklist` before dry-run starts — ask him for the list at Task 7 and add the exact pairs.

- [ ] **Step 3: Verify the pairlist against live Kraken**

Run: `cd ~/YOLO && docker compose run --rm freqtrade test-pairlist --config /freqtrade/config-paper.json`

Expected: pulls the Docker image (first run), then prints a JSON-ish list of ~10–30 real Kraken USD pairs (exact contents vary with the market; typically includes a mix of majors and movers). Must NOT contain any `USDT/USD`-style stablecoin pair. If it errors on a filter name, check the installed freqtrade version's docs for renamed pairlist options and fix the config — do not delete the filter.

- [ ] **Step 4: Record resolved versions**

Run: `docker compose run --rm freqtrade --version`
Append the output version line as a comment line at the bottom of `README.md` under a `## Versions` heading (e.g. `Freqtrade 2026.x via freqtradeorg/freqtrade:stable, resolved 2026-07-18`).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml config-paper.json README.md user_data/strategies/.gitkeep
git commit -m "Add Freqtrade docker setup and dynamic whole-market pairlist config (paper mode)"
```

---

### Task 2: Pure-pandas signal module (TDD)

**Files:**
- Create: `user_data/strategies/momentum_signals.py`
- Test: `tests/test_momentum_signals.py`
- Create: `requirements-dev.txt` (contents: `pandas` and `pytest`, one per line)

**Interfaces:**
- Produces: `add_indicators(df: DataFrame, params: dict) -> DataFrame` (adds `pct_change`, `vol_avg` columns) and `entry_mask(df: DataFrame, params: dict) -> Series[bool]`; `DEFAULT_PARAMS` dict with keys `momentum_candles`, `momentum_threshold`, `volume_window`, `volume_mult`. Task 3's strategy imports exactly these names.

- [ ] **Step 1: Set up the local test venv**

```bash
cd ~/YOLO && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_momentum_signals.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import DEFAULT_PARAMS, add_indicators, entry_mask


def make_df(closes, volumes):
    return pd.DataFrame({"close": closes, "volume": volumes})


def test_pump_with_volume_spike_signals_entry():
    # 60 flat candles, then 8 candles pumping +5% total on 3x volume
    closes = [100.0] * 60 + [100.0 * (1 + 0.05 * (i + 1) / 8) for i in range(8)]
    volumes = [1000.0] * 60 + [3000.0] * 8
    df = add_indicators(make_df(closes, volumes), DEFAULT_PARAMS)
    mask = entry_mask(df, DEFAULT_PARAMS)
    assert bool(mask.iloc[-1]) is True


def test_flat_market_never_signals():
    df = add_indicators(make_df([100.0] * 80, [1000.0] * 80), DEFAULT_PARAMS)
    assert entry_mask(df, DEFAULT_PARAMS).sum() == 0


def test_pump_without_volume_does_not_signal():
    closes = [100.0] * 60 + [100.0 * (1 + 0.05 * (i + 1) / 8) for i in range(8)]
    volumes = [1000.0] * 68  # no volume confirmation
    df = add_indicators(make_df(closes, volumes), DEFAULT_PARAMS)
    assert bool(entry_mask(df, DEFAULT_PARAMS).iloc[-1]) is False


def test_warmup_rows_never_signal():
    # Fewer rows than the volume window: vol_avg is NaN, mask must be all False
    df = add_indicators(make_df([100.0] * 10, [1000.0] * 10), DEFAULT_PARAMS)
    assert entry_mask(df, DEFAULT_PARAMS).sum() == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/ -v`
Expected: FAIL/ERROR with `ModuleNotFoundError: No module named 'momentum_signals'`

- [ ] **Step 4: Write the module**

```python
# user_data/strategies/momentum_signals.py
"""Pure-pandas momentum signal math, kept freqtrade-free so it can be unit
tested locally and reused verbatim by the backtest harness."""
import pandas as pd

DEFAULT_PARAMS = {
    "momentum_candles": 8,      # lookback: 8 x 15m = 2 hours
    "momentum_threshold": 0.03,  # +3% over the lookback
    "volume_window": 48,         # rolling volume baseline: 12 hours
    "volume_mult": 2.0,          # current volume must be 2x baseline
}


def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    df = df.copy()
    df["pct_change"] = df["close"].pct_change(params["momentum_candles"])
    df["vol_avg"] = df["volume"].rolling(params["volume_window"]).mean()
    return df


def entry_mask(df: pd.DataFrame, params: dict) -> pd.Series:
    return (
        (df["pct_change"] > params["momentum_threshold"])
        & df["vol_avg"].notna()
        & (df["volume"] > params["volume_mult"] * df["vol_avg"])
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add user_data/strategies/momentum_signals.py tests/test_momentum_signals.py requirements-dev.txt
git commit -m "Add momentum signal module with unit tests (pump+volume in, flat/quiet out)"
```

---

### Task 3: MemeMomentum strategy

**Files:**
- Create: `user_data/strategies/MemeMomentum.py`

**Interfaces:**
- Consumes: `momentum_signals.add_indicators`, `entry_mask`, `DEFAULT_PARAMS` from Task 2.
- Produces: strategy class `MemeMomentum` (the name `config-paper.json` and docker-compose already reference).

- [ ] **Step 1: Write the strategy**

```python
# user_data/strategies/MemeMomentum.py
from datetime import datetime, timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

from momentum_signals import DEFAULT_PARAMS, add_indicators, entry_mask


class MemeMomentum(IStrategy):
    """Spec 2026-07-18 §5: long-only 15m momentum. Entries = pump + volume spike.
    Exits = ROI ladder, hard stop, trailing stop, stagnation timeout.
    Protections here implement spec §6 and are never weakened (spec §8.5)."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 60  # > volume_window(48) + momentum_candles(8)

    params = DEFAULT_PARAMS

    # Exit ladder (minutes: profit). Tuned in Task 6; these are starting values.
    minimal_roi = {"0": 0.10, "120": 0.04, "360": 0.02}
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    stagnation_hours = 12  # close flat trades after this long

    @property
    def protections(self):
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 4},
            {
                "method": "StoplossGuard",
                "lookback_period_candles": 96,
                "trade_limit": 4,
                "stop_duration_candles": 48,
                "only_per_pair": False,
            },
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": 672,
                "trade_limit": 5,
                "max_allowed_drawdown": 0.15,
                "stop_duration_candles": 1344,
            },
        ]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return add_indicators(dataframe, self.params)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[entry_mask(dataframe, self.params), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe  # exits handled by ROI/stoploss/trailing/custom_exit

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        if (current_time - trade.open_date_utc) > timedelta(hours=self.stagnation_hours) \
                and current_profit < 0.01:
            return "stagnation_timeout"
        return None
```

- [ ] **Step 2: Verify freqtrade loads it**

Run: `docker compose run --rm freqtrade list-strategies --config /freqtrade/config-paper.json`
Expected: a table listing `MemeMomentum` with status OK (not "duplicate" or "error"). An import error here usually means `momentum_signals.py` isn't in the same strategies directory.

- [ ] **Step 3: Local tests still pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: 4 passed

- [ ] **Step 4: Commit**

```bash
git add user_data/strategies/MemeMomentum.py
git commit -m "Add MemeMomentum strategy: momentum entries, layered exits, hard-coded protections"
```

---

### Task 4: Historical data download

**Files:**
- Create: `scripts/make_pairs_file.py`
- Create: `scripts/download_data.sh`

**Interfaces:**
- Produces: `user_data/pairs_usd.json` (JSON array of pair strings; gitignored with the data), 15m candle data under `user_data/data/kraken/` as `.feather` files named like `DOGE_USD-15m.feather`. Task 5 reads exactly these.

- [ ] **Step 1: Write the pairs-file generator**

```python
# scripts/make_pairs_file.py
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
```

(If `list-pairs --print-json` output is not parseable as described, inspect raw stdout and adjust the parsing — the goal is simply the full USD pair array minus blacklist. If more than ~80 pairs survive, keep all; the `TOP_N` cap is applied by download time-budget below, not by deleting pairs here.)

- [ ] **Step 2: Generate the pairs file**

Run: `cd ~/YOLO && python3 scripts/make_pairs_file.py`
Expected: `Wrote <N> pairs to user_data/pairs_usd.json` where N is roughly 100–300. Spot-check the file: contains `"DOGE/USD"`, does NOT contain `"USDT/USD"`.

- [ ] **Step 3: Write the download script**

```bash
#!/usr/bin/env bash
# scripts/download_data.sh — download 15m Kraken history for the backtest.
# Kraken's candle API only serves ~720 recent candles, so freqtrade must
# rebuild candles from raw trades (--dl-trades). This is SLOW (hours; Kraken
# rate-limits). Run it overnight; it is resumable — rerunning skips finished pairs.
set -euo pipefail
cd "$(dirname "$0")/.."

TIMERANGE="${1:-20260101-20260715}"

docker compose run --rm freqtrade download-data \
  --config /freqtrade/config-paper.json \
  --pairs-file /freqtrade/user_data/pairs_usd.json \
  -t 15m \
  --dl-trades \
  --timerange "$TIMERANGE"
```

Run: `chmod +x scripts/download_data.sh`

- [ ] **Step 4: Smoke-test the download on one pair**

Run: `docker compose run --rm freqtrade download-data --config /freqtrade/config-paper.json --pairs DOGE/USD -t 15m --dl-trades --timerange 20260601-20260715`
Expected: progress logs ending with a saved dataset; `ls user_data/data/kraken/` shows `DOGE_USD-15m.feather`.

- [ ] **Step 5: Kick off the full download**

Run: `./scripts/download_data.sh 20260101-20260715` (background/overnight; hours of runtime is normal)
Expected on completion: `ls user_data/data/kraken/*.feather | wc -l` is within a few dozen of the pairs-file count (some pairs are too new to have full history — that's fine and the harness tolerates it).

- [ ] **Step 6: Commit (scripts only — data is gitignored)**

```bash
git add scripts/make_pairs_file.py scripts/download_data.sh
git commit -m "Add Kraken USD pair listing and historical data download scripts"
```

---

### Task 5: Look-ahead-safe rolling backtest harness

**Files:**
- Create: `scripts/rolling_backtest.py`
- Test: `tests/test_rolling_ranking.py`

**Interfaces:**
- Consumes: feather files from Task 4 (`user_data/data/kraken/<PAIR>-15m.feather` with columns `date, open, high, low, close, volume`), `config-paper.json`.
- Produces: `rank_pairs_for_month(data_dir: Path, month_start: pd.Timestamp, top_n: int) -> list[str]` (importable), and CLI output `user_data/backtest_results/rolling_summary.md` + `rolling_summary.json` with keys `total_trades`, `trades_per_week`, `total_profit_pct`, `max_drawdown_pct`, `months`, `gate_pass`.

- [ ] **Step 1: Write the failing ranking test**

```python
# tests/test_rolling_ranking.py
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from rolling_backtest import rank_pairs_for_month


def _write_feather(tmp_path, pair, month, price, volume):
    # 2000 x 15m candles ≈ 20.8 days — stays inside one month and clears the
    # harness's 500-candle minimum for rankability
    dates = pd.date_range(month, periods=2000, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "date": dates, "open": price, "high": price, "low": price,
        "close": price, "volume": volume,
    })
    df.to_feather(tmp_path / f"{pair}-15m.feather")


def test_ranks_by_prior_month_quote_volume_only(tmp_path):
    # Data exists ONLY in June; ranking for July must use June's volume.
    _write_feather(tmp_path, "BIG_USD", "2026-06-01", price=2.0, volume=500.0)   # $1000/candle
    _write_feather(tmp_path, "SMALL_USD", "2026-06-01", price=1.0, volume=10.0)  # $10/candle
    ranked = rank_pairs_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"), top_n=1)
    assert ranked == ["BIG/USD"]


def test_pair_with_no_prior_data_is_excluded(tmp_path):
    # Data starts in July; for July's ranking (prior month = June) it must not appear.
    _write_feather(tmp_path, "NEW_USD", "2026-07-01", price=1.0, volume=1000.0)
    ranked = rank_pairs_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"), top_n=5)
    assert ranked == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_rolling_ranking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rolling_backtest'`

- [ ] **Step 3: Write the harness**

```python
#!/usr/bin/env python3
# scripts/rolling_backtest.py
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
         "--fee", str(FEE), "--export", "trades"],
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
```

- [ ] **Step 4: Ranking tests pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: 6 passed (4 signal + 2 ranking)

- [ ] **Step 5: Run the harness for real**

Run: `python3 scripts/rolling_backtest.py 2026-02 2026-07`
Expected: per-month progress lines, then a JSON summary. If `stats` key names don't match the installed freqtrade version's backtest output, adjust `run_month`/`_load_stats` to the actual result schema (inspect the newest file in `user_data/backtest_results/`) — the summary numbers, not the field names, are the contract.

- [ ] **Step 6: Commit (including the summary markdown, which IS tracked)**

```bash
git add scripts/rolling_backtest.py tests/test_rolling_ranking.py
git add -f user_data/backtest_results/rolling_summary.md
git commit -m "Add look-ahead-safe rolling backtest harness with spec gate check"
```

---

### Task 6: Tuning to the acceptance gate

**Files:**
- Modify: `user_data/strategies/momentum_signals.py` (DEFAULT_PARAMS values only)
- Modify: `user_data/strategies/MemeMomentum.py` (minimal_roi / stoploss / trailing values only)
- Create: `docs/backtests.md`

**Interfaces:**
- Consumes: Task 5's harness and `rolling_summary.json` `gate_pass` field.

- [ ] **Step 1: Baseline run** — run `python3 scripts/rolling_backtest.py 2026-02 2026-07`; record the summary table in `docs/backtests.md` under a heading with the exact params used.

- [ ] **Step 2: Parameter sweep** — vary ONE parameter at a time, rerun, record each row in `docs/backtests.md`. Sweep ranges: `momentum_threshold` ∈ {0.02, 0.03, 0.04, 0.05}; `volume_mult` ∈ {1.5, 2.0, 3.0}; `stoploss` ∈ {-0.05, -0.06, -0.08}; `minimal_roi` "0" entry ∈ {0.06, 0.10, 0.15}. Each run is one line: params → trades/week, profit %, max DD %.

- [ ] **Step 3: Select** — choose the config that passes the gate (`gate_pass: true`) with the best profit-to-drawdown balance. If NOTHING passes the gate, stop and report to Austin with the table — do not deploy a failing strategy and do not silently loosen the gate (spec §9).

- [ ] **Step 4: Lock in** — set the chosen values in the two strategy files, rerun the harness once to confirm `gate_pass: true` with the committed values, and confirm `.venv/bin/pytest tests/ -v` still passes (adjust test pump sizes only if a threshold change legitimately requires it).

- [ ] **Step 5: Commit**

```bash
git add user_data/strategies/ docs/backtests.md
git add -f user_data/backtest_results/rolling_summary.md
git commit -m "Tune momentum parameters to pass the backtest gate; record the sweep"
```

---

### Task 7: Dry-run deployment package (Windows)

**Files:**
- Create: `docs/DEPLOY-WINDOWS.md`
- Create: `scripts/health_check.py`
- Create: `.env.example`
- Modify: `README.md` (replace the "Running it" placeholder section with real commands)
- Modify: `config-paper.json` (add Austin's personal holdings to `pair_blacklist`)

**Interfaces:**
- Consumes: the running bot's REST API (enabled in Task 1's config), `freqtrade-client` pip package.

- [ ] **Step 1: Ask Austin for his current Kraken holdings** and add each as an exact pair (e.g. `"XBT/USD"`) at the top of `pair_blacklist` in `config-paper.json`, with no other config changes. (Spec §8.6 — the bot never trades his personal bags.)

- [ ] **Step 2: Write `.env.example`**

```bash
# Copy to .env on the machine running the bot. Never commit .env.
FT_JWT_SECRET=generate-a-long-random-string
FT_PASS=pick-a-real-password
```

- [ ] **Step 3: Write `scripts/health_check.py`**

```python
#!/usr/bin/env python3
"""Daily dry-run health check (spec §5: zero trades in 48h = fault).
Usage: FT_PASS=... python3 scripts/health_check.py
Requires: pip install freqtrade-client"""
import os
import sys
from datetime import datetime, timedelta, timezone

from freqtrade_client import FtRestClient

client = FtRestClient("http://127.0.0.1:8080", "yolo", os.environ["FT_PASS"])
state = client.show_config()
print(f"Bot state: {state['state']}, dry_run: {state['dry_run']}")
whitelist = client.whitelist()
print(f"Watching {whitelist['length']} pairs: {', '.join(whitelist['whitelist'][:10])}...")

trades = client.trades(limit=100)
cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
recent = [t for t in trades.get("trades", [])
          if datetime.fromisoformat(t["open_date"].replace("Z", "+00:00")) > cutoff]
open_count = client.count().get("current", 0)
print(f"Open trades: {open_count}; trades opened in last 48h: {len(recent)}")

if not recent and not open_count:
    print("FAULT: zero trades in 48h — investigate today (spec §5). "
          "Check whitelist churn, threshold too strict, or bot stalled.")
    sys.exit(1)
print("OK")
```

- [ ] **Step 4: Write `docs/DEPLOY-WINDOWS.md`** — exact steps, no jargon:

```markdown
# Running the bot on the Windows desktop (paper mode)

One-time setup:
1. Install Docker Desktop for Windows (docker.com) and start it. Enable
   "Start Docker Desktop when you sign in to your computer" in its settings.
2. Install Git for Windows (git-scm.com), open "Git Bash".
3. In Git Bash: `git clone https://github.com/asandler2727-coder/yolo.git && cd yolo`
4. `cp .env.example .env`, then edit `.env` in Notepad: set a long random
   FT_JWT_SECRET and a real FT_PASS.

Start the bot: `docker compose up -d`
Watch it: open http://127.0.0.1:8080 in a browser — login `yolo` / your FT_PASS.
Daily check: `docker compose logs --since 24h freqtrade | tail -50` and run
  `py scripts/health_check.py` (needs `py -m pip install freqtrade-client` once).
Stop the bot (kill switch): `docker compose down`
Update to latest code: `git pull && docker compose up -d --force-recreate`

The 2-week dry-run clock (spec §9) starts at the first `docker compose up -d`
and the decision date goes in docs/backtests.md the same day.
```

- [ ] **Step 5: Verify the health check against a locally-running bot**

Run (Mac): `docker compose up -d && sleep 90 && FT_PASS=yolo-dev .venv/bin/python scripts/health_check.py; docker compose down`
(First: `.venv/bin/pip install freqtrade-client`.)
Expected: prints bot state `running`, `dry_run: True`, a real whitelist, and (since the bot just started) the FAULT line with exit 1 — which proves the fault path works. The `docker compose down` still runs.

- [ ] **Step 6: Update README's "Running it" section** to point at `docs/DEPLOY-WINDOWS.md` and show the Mac-side equivalents (`docker compose up -d` / FreqUI / `docker compose down`).

- [ ] **Step 7: Commit**

```bash
git add docs/DEPLOY-WINDOWS.md scripts/health_check.py .env.example README.md config-paper.json
git commit -m "Add Windows deployment guide, daily health check, and holdings blacklist"
```

---

### Task 8 (build during the dry-run window): Sentiment advisor, advisory mode

**Files:**
- Create: `sentiment/PROMPT.md`
- Create: `scripts/apply_sentiment.py`
- Create: `sentiment/reports/.gitkeep`

**Interfaces:**
- Consumes: a Grok X-sentiment run (via the Grok Build plugin / `whathappened`-style analysis) producing `sentiment/reports/YYYY-MM-DD.md` + `sentiment/cooling.json` (JSON array of pair strings to blacklist).
- Produces: updated `pair_blacklist` in `config-paper.json` (the only thing sentiment may touch — spec §7).

- [ ] **Step 1: Write `sentiment/PROMPT.md`** (the standing prompt given to Grok, 1–2×/day):

```markdown
Analyze the last 24h of crypto conversation on X. Output two sections:
1. HEATING: coins with sharply rising mention volume/enthusiasm that trade on
   Kraken vs USD — for each: pair, one-line why, links to 2-3 representative posts.
2. COOLING: coins whose hype collapsed or turned negative (rug accusations,
   exploit news, dev drama) that trade on Kraken vs USD — same format.
Be skeptical of coordinated shilling; note it when suspected. End with a JSON
array of the COOLING pairs only, e.g. ["PEPE/USD","WIF/USD"], on its own line.
Save the full analysis as sentiment/reports/<today>.md and the JSON array as
sentiment/cooling.json.
```

- [ ] **Step 2: Write `scripts/apply_sentiment.py`**

```python
#!/usr/bin/env python3
"""Advisory-mode apply step (spec §7): merge sentiment/cooling.json into the
paper config's pair_blacklist. Prints the diff; never touches anything else.
A pair listed in cooling.json stays blacklisted until removed manually."""
import json
from pathlib import Path

cfg_path = Path("config-paper.json")
cfg = json.loads(cfg_path.read_text())
cooling = json.loads(Path("sentiment/cooling.json").read_text())

blacklist = cfg["exchange"]["pair_blacklist"]
added = [p for p in cooling if p not in blacklist]
blacklist.extend(added)
cfg_path.write_text(json.dumps(cfg, indent=4) + "\n")
print(f"Added to blacklist: {added or 'nothing new'}")
print("Restart the bot (docker compose up -d --force-recreate) to apply.")
```

- [ ] **Step 3: Test the apply script** — create `sentiment/cooling.json` containing `["PEPE/USD"]`, run `python3 scripts/apply_sentiment.py`, expect `Added to blacklist: ['PEPE/USD']` and the pair present in `config-paper.json`; then `git checkout config-paper.json && rm sentiment/cooling.json` to undo the test.

- [ ] **Step 4: Commit**

```bash
git add sentiment/PROMPT.md scripts/apply_sentiment.py sentiment/reports/.gitkeep
git commit -m "Add sentiment advisor prompt and advisory blacklist apply step"
```

Note: HEATING coins are report-only in this phase (awareness, not action) — injecting them into the dynamic whitelist is a possible later step (freqtrade's RemotePairList) and is deliberately out of this plan. Automation of the daily Grok run also waits until the advisory loop proves useful (spec §7).

---

## Not in this plan (deliberate)

Live-mode config, Kraken API key setup, and key rotation — those happen manually at the go-live gate with Austin, per spec §8/§9. Hyperopt, Telegram, RemotePairList sentiment injection, and any cloud deployment — YAGNI until the dry-run proves the core loop.
