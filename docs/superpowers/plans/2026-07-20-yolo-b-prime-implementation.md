# b′ Limit-Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **This session:** executed inline (small, tightly-coupled plan; Austin approved the spec and the full pipeline through STOP-with-results).

**Goal:** Implement the approved b′ spec (`docs/superpowers/specs/2026-07-20-yolo-b-prime-limit-entry.md`): entries become resting limit orders 2% below the signal price with a 4h timeout; run one Feb–Jul rolling backtest with fill diagnostics; record and stop.

**Architecture:** One pure helper in `momentum_signals.py` (tested), one `custom_entry_price` override in `MemeMomentum.py`, two config knobs in `config-paper.json` (flow into the harness's tmp config automatically), two small diagnostic scripts, zero changes to signals/exits/protections/harness logic.

**Tech Stack:** Python/pandas, pytest, freqtrade 2026.4 via docker compose, existing rolling harness.

## Global Constraints (from the spec — verbatim)

- `entry_limit_depth = 0.02`, unfilled-entry timeout 240 minutes — single pre-registered configuration, **no sweeps**.
- Signals, exits, protections, pairlist, `--fee 0.004`, `--enable-protections` all unchanged.
- `custom_price_max_distance_ratio: 0.05` must be set explicitly (default 0.02 would clamp at our depth).
- Result zips parsed from freqtrade stdout, never `.last_result.json`.
- Gate unchanged; record honestly whatever comes out; STOP after recording.

**Success criteria (all must hold before "done"):**
1. `pytest tests/` green including new limit-price tests.
2. Smoke month (May) run produces trades whose fill prices sit ~2% below the placement price (clamp ruled out), fewer fills than signals.
3. Full Feb–Jul run (6 months) completes; regime audit shows 100% in-regime entries; fill-rate table computed.
4. Results + diagnostics recorded in `docs/backtests.md`; committed and pushed; ledger updated; final report delivered; STOP.

---

### Task 1: Pure limit-price helper (TDD)

**Files:**
- Modify: `user_data/strategies/momentum_signals.py` (add param + one function)
- Test: `tests/test_momentum_signals.py` (append)

**Interfaces:**
- Produces: `limit_entry_price(proposed_rate: float, depth: float) -> float`, `DEFAULT_PARAMS["entry_limit_depth"] == 0.02` — consumed by Task 2.

- [ ] **Step 1: failing tests**

```python
# append to tests/test_momentum_signals.py
from momentum_signals import limit_entry_price


def test_limit_entry_price_is_depth_below_proposed():
    assert limit_entry_price(100.0, 0.02) == pytest.approx(98.0)
    assert limit_entry_price(0.004321, 0.02) == pytest.approx(0.004321 * 0.98)


def test_limit_entry_depth_default_registered():
    assert DEFAULT_PARAMS["entry_limit_depth"] == 0.02
```

(`DEFAULT_PARAMS` and `pytest` are already imported at the top of the test file; verify, add if missing.)

- [ ] **Step 2: run, expect FAIL** — `.venv/bin/pytest tests/test_momentum_signals.py -q` → ImportError/KeyError.

- [ ] **Step 3: implement**

```python
# momentum_signals.py — DEFAULT_PARAMS gains (with the other entry keys):
    # b' (2026-07-20): entry rests as a limit this far below the signal-time
    # proposed rate, buying the measured post-signal shakeout. Spec-frozen.
    "entry_limit_depth": 0.02,

# and after entry_mask():
def limit_entry_price(proposed_rate: float, depth: float) -> float:
    """b' entry pricing: rest a limit `depth` below the proposed market rate."""
    return proposed_rate * (1.0 - depth)
```

- [ ] **Step 4: run, expect PASS** — full `.venv/bin/pytest tests/ -q` (17 old + new green).
- [ ] **Step 5: commit** — "Add b-prime limit entry price helper (TDD)".

### Task 2: Strategy + config wiring

**Files:**
- Modify: `user_data/strategies/MemeMomentum.py`
- Modify: `config-paper.json` (read it first; extend, never regenerate)

**Interfaces:**
- Consumes: Task 1's helper/param.
- Produces: `MemeMomentum.custom_entry_price(...)`; config keys `unfilledtimeout.entry = 240` (minutes) and `custom_price_max_distance_ratio = 0.05`.

- [ ] **Step 1: strategy override** (freqtrade calls with keyword args; `**kwargs` absorbs version extras like `side`):

```python
from momentum_signals import (
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    limit_entry_price,
    regime_mask_from_btc,
    resample_1h,
)

    def custom_entry_price(self, pair: str, trade, current_time: datetime,
                           proposed_rate: float, entry_tag, **kwargs) -> float:
        # b' (spec 2026-07-20): rest the entry 2% below the signal-time price
        # and let unfilledtimeout cancel it; requires the config to lift
        # custom_price_max_distance_ratio above the depth or freqtrade clamps.
        return limit_entry_price(proposed_rate, self.params["entry_limit_depth"])
```

Docstring: update the class docstring's entry sentence to mention the b′ limit entry + spec file.

- [ ] **Step 2: config knobs** — in `config-paper.json` add/extend (exact placement after reading the file):

```json
"unfilledtimeout": {"entry": 240, "exit": 10, "unit": "minutes"},
"custom_price_max_distance_ratio": 0.05,
```

If an `unfilledtimeout` block exists, change only `entry` (and keep its unit consistent — convert 240 accordingly).

- [ ] **Step 3: sanity** — `.venv/bin/pytest tests/ -q` still green (strategy file isn't imported by local tests; this guards the signals module). `python3 -c "import json; json.load(open('config-paper.json'))"` parses.
- [ ] **Step 4: commit** — "Wire b-prime limit entry into strategy and paper config".

### Task 3: Fill-depth verifier

**Files:**
- Create: `scripts/verify_fill_depth.py`

**Interfaces:**
- Consumes: result zip path(s) argv; candle feathers.
- Produces: per-zip report — mean/median/min discount of `open_rate` vs the placement-candle close, share of trades at ≥1.5% discount, any trade discounted <1.5% listed (clamp suspicion). Placement candle: from the trade's `orders[]` entry-order timestamp when present, else the candle before `open_date`.

- [ ] **Step 1: write it** (inspect one b′ zip's trade dict for `orders[]` first; code below assumes fallback path works regardless):

```python
#!/usr/bin/env python3
"""Assert b' fills actually sit ~2% below the price at order placement.

Catches the freqtrade custom_price_max_distance_ratio clamp (spec s6.1): if
the config knob were ignored, discounts would collapse toward 0-2% of the
CURRENT rate at fill time instead of the placement-time rate.
Usage: verify_fill_depth.py result1.zip [result2.zip ...]
"""
import json, sys, zipfile
from pathlib import Path
import pandas as pd

DATA = Path("user_data/data/kraken")
_cache = {}

def candles(pair):
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
        _cache[pair] = df.set_index("date").sort_index()
    return _cache[pair]

def trades_from_zip(zp):
    with zipfile.ZipFile(zp) as z:
        inner = [n for n in z.namelist() if n.endswith(".json")
                 and not n.endswith("_config.json") and not n.endswith(".meta.json")]
        return json.loads(z.read(inner[0]))["strategy"]["MemeMomentum"]["trades"]

def placement_time(t):
    for o in t.get("orders", []):
        if o.get("ft_order_side") in ("buy", "enter_long"):
            ts = o.get("order_date") or o.get("order_timestamp")
            if ts is not None:
                return pd.Timestamp(ts, unit="ms", tz="UTC") if isinstance(ts, (int, float)) else pd.Timestamp(ts, tz="UTC")
    return pd.Timestamp(t["open_date"]) - pd.Timedelta(minutes=15)

def main():
    rows = []
    for zp in sys.argv[1:]:
        for t in trades_from_zip(zp):
            ref_ts = placement_time(t)
            df = candles(t["pair"])
            ref = df.loc[:ref_ts].iloc[-1]["close"] if len(df.loc[:ref_ts]) else None
            if ref is None:
                continue
            rows.append({"pair": t["pair"], "open_date": t["open_date"],
                         "discount": 1 - t["open_rate"] / ref})
    d = pd.DataFrame(rows)
    print(f"{len(d)} fills | discount vs placement-candle close: "
          f"mean {d.discount.mean():+.2%}  median {d.discount.median():+.2%}  "
          f"min {d.discount.min():+.2%}")
    shallow = d[d.discount < 0.015]
    print(f"fills with <1.5% discount (clamp suspicion): {len(shallow)}")
    if len(shallow):
        print(shallow.to_string(index=False))

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: no unit test** (diagnostic script; exercised by Task 5 smoke on real output — that run is its test).

### Task 4: Signal counter (fill-rate diagnostics)

**Files:**
- Create: `scripts/count_signals.py`

**Interfaces:**
- Consumes: `rank_pairs_for_month` from `scripts/rolling_backtest.py`; `momentum_signals` pure functions; BTC feather for the regime (reconstruction copied from `scripts/verify_regime_gating.py` — read it first and reuse its exact offset logic).
- Produces: per-month `signal candles` count over the ranked-30 universe, printed table — denominator for fill rate (fills come from the result zips).

- [ ] **Step 1: write it** — for each month Feb..Jul: rank pairs (same function the harness uses), for each pair load candles from (month_start − 7 days warmup) to month_end, `add_indicators` + `entry_mask` with the BTC regime series merged the same way `verify_regime_gating.py` does (+45m availability offset), count `mask & in-month` candles; print month, pairs, signal-candle count. Import what's importable; copy the ~15 regime lines if the audit script isn't import-clean, with a comment naming the source.
- [ ] **Step 2: sanity** — run for 2026-05; signal count must be ≥ v2's May trade count (44) since v2 entries are a subset of signals (slot-limited). If lower, the reconstruction is wrong — fix before proceeding.
- [ ] **Step 3: commit** Tasks 3+4 together — "Add b-prime fill-depth and signal-count diagnostics".

### Task 5: Smoke backtest (May 2026)

- [ ] **Step 1:** `.venv/bin/python scripts/rolling_backtest.py 2026-05 2026-05` (harness unchanged; picks up new strategy + config via tmp config).
- [ ] **Step 2: assert** on the printed zip: `.venv/bin/python scripts/verify_fill_depth.py user_data/backtest_results/<zip>` → median discount in ~1.5–2.5% band, zero/near-zero clamp suspicions; `grep custom_price_max_distance_ratio user_data/tmp_bt_config.json` shows 0.05; trade count > 0 and < v2's May 44 (fewer fills than signals).
- [ ] **Step 3:** if any assertion fails → stop, diagnose against spec §6 (clamp, timeout units, signature), fix, rerun smoke. Two failed cycles → stop and report per the 10-minute rule.

### Task 6: Full run, record, STOP

- [ ] **Step 1:** `.venv/bin/python scripts/rolling_backtest.py 2026-02 2026-07` (six months, one run).
- [ ] **Step 2:** diagnostics: `verify_fill_depth.py` over all six zips; `verify_regime_gating.py` over all six zips (expect 100% in-regime); `count_signals.py` for fill-rate table (fills/signals per month).
- [ ] **Step 3:** gate arithmetic: total profit sign at 0.4% fees; in-regime trades/week vs ≥5; max monthly DD (flag >25%).
- [ ] **Step 4:** append results section to `docs/backtests.md` (per-month table with zip names, fill diagnostics, gate verdict, in-sample caveat verbatim from spec §4).
- [ ] **Step 5:** commit + push; update `.handoff/task.md` (result + STOPPED-for-Austin next action); deliver report; STOP — pass → Aug+/dry-run decision is Austin's; fail → option (c) decision is Austin's.
