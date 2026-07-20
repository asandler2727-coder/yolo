# Family A Range-Breakout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **This session:** Austin mandated inline execution (superpowers:executing-plans), TDD, commits at natural checkpoints.

**Goal:** Build the approved family-A range-breakout strategy (two universe arms), verify its mechanics on a smoke month, run the pre-dev survivorship check, and record the dev baseline (iteration 1 of ≤15) — then stop and report to Austin.

**Architecture:** Pure-pandas signal math in `momentum_signals.py` (freqtrade-free, unit-tested), wired into the existing `MemeMomentum` strategy class. The rolling monthly harness gains an arm-D ranking mode and per-arm fees. New diagnostics scripts parse captured freqtrade stdout and result zips. Every number comes from `docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md`.

**Tech Stack:** Python 3 + pandas, pytest, freqtrade via `docker compose run`, feather candle files under `user_data/data/kraken/`.

## Global Constraints

- Spec is the source of truth: `docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md` (§9 records the audit chain and Austin's amendments).
- Entry defaults: `range_lookback=48` (prior candles, shift(1), current bar excluded), `range_max_width=0.06`, `max_extension=0.015`, `volume_mult=2.0`, `volume_window=48`. Regime unchanged from v2: BTC 1h close>EMA50 & EMA20>EMA50, +45m offset, fail-closed.
- Anti-chase cap enforced AT THE FILL against the signal-bar-frozen `entry_cap`; a rolling reference is forbidden. Tests must assert BOTH bounds: signal close AND fill rate.
- Entries are market orders: remove b′'s `custom_entry_price`; `unfilledtimeout.entry` 240→10.
- Sizing: `custom_stake_amount` = 10% of current total equity, `max_open_trades: 10`, `dry_run_wallet: 750`; stakes below a pair's Kraken minimum are skipped and logged.
- Exits: stop −4%; ROI `{0: 0.05, 240: 0.03, 480: 0.015}`; trailing 0.012 after 0.03 offset; NO stagnation exit by default (timed cuts {4h, 8h, 12h} are dev knobs only). Protections untouched; `--enable-protections` in every run.
- Arm L: floor $250k/day then top-30, `--fee 0.0045`. Arm D: rank full USD set by prior-month volume, slice ranks 31–100, THEN drop <$100k/day, `--fee 0.006`. Arm D is its own code path with its own tests.
- Parse backtest results from freqtrade stdout only — never `.last_result.json` (Docker bind-mount stale-pointer bug).
- `dry_run` stays true; no live keys; no `config-live.json`.
- NEVER run the holdout (2025-09→2026-01) or the kill window (2026-02→07). Dev window is 2024-02→2025-08 only.
- Suppress pandas/pyarrow FutureWarnings in scripts (they drown output). Docker backtests run ~5–8s per month per arm.
- Plain-English commit messages; commit and push without asking (Austin's git autonomy rule).

## File Structure

| File | Responsibility |
|---|---|
| `user_data/strategies/momentum_signals.py` | Rewritten: family-A breakout math, pure pandas (regime helpers kept verbatim) |
| `tests/test_momentum_signals.py` | Rewritten: golden breakout fixture + one-gate-off negatives + look-ahead + cap-freeze tests |
| `user_data/strategies/MemeMomentum.py` | Modified: fill veto, 10%-equity sizing, family-A exits, stagnation off |
| `config-paper.json` | Modified: max_open_trades 10, stake unlimited, entry timeout 10 |
| `scripts/rolling_backtest.py` | Modified: shared volume collector, arm-D ranking mode, per-arm fee, per-run log capture |
| `tests/test_rolling_ranking.py` | Extended: arm-D ordering tests, fee pins; arm-L tests unchanged |
| `scripts/verify_breakout_cap.py` | New: both-bounds cap check per fill, tick-tolerant |
| `scripts/run_diagnostics.py` | New: vetoes, per-trade stats, hold distribution, slot occupancy, DEV row |
| `tests/test_diagnostics.py` | New: unit tests for the pure diagnostic functions |
| `docs/backtests.md` | Appended: survivorship check section, family-A DEV table |

---

### Task 1: Family-A signal math (TDD rewrite of momentum_signals)

**Files:**
- Modify: `user_data/strategies/momentum_signals.py` (full rewrite; keep `resample_1h`, `regime_mask_from_btc` verbatim)
- Modify: `tests/test_momentum_signals.py` (full rewrite; keep the resample/regime tests verbatim)

**Interfaces:**
- Consumes: nothing new (pandas only).
- Produces (Task 2 and 4 rely on these exact names):
  - `DEFAULT_PARAMS: dict` with keys `regime_ema_fast, regime_ema_slow, range_lookback, range_max_width, max_extension, volume_window, volume_mult`
  - `add_indicators(df, params) -> DataFrame` adding columns `range_high, range_low, range_width, vol_avg, entry_cap`
  - `entry_mask(df, params, regime_ok) -> Series[bool]`
  - `signal_bar_cap(df, fill_time) -> float | None` (df needs `date`, `enter_long`, `entry_cap` columns)
  - `fill_allowed(fill_rate, cap) -> bool`
  - `resample_1h(df)`, `regime_mask_from_btc(btc_1h, params)` — unchanged from v2

- [ ] **Step 1: Write the new test file (failing)**

Replace `tests/test_momentum_signals.py` entirely with:

```python
"""Family-A range-breakout signal tests.

Design: one GOLDEN breakout fixture (regime up + tight 12h coil + close above
the range high on expanded volume, inside the anti-chase cap). Every negative
is the golden fixture with exactly ONE gate perturbed, so a red test names the
gate that broke.

Fixture geometry:
- 60 coil bars (open 101, high 103, low 100, close 101.5, vol 1000) then one
  firing bar closing 103.5 on volume 2500. Range over the PRIOR 48 candles
  (shift(1)): high 103, low 100, width 3.0% <= 6%. Cap = 103*1.015 = 104.545.
  vol_avg at the firing bar = (47*1000 + 2500)/48 = 1031.25; 2x = 2062.5.
- The look-ahead test gives the firing bar a monster 200.0 wick: if the range
  wrongly included the current bar, range_high would be 200 and the breakout
  test (close > range_high) would fail — so the signal firing PROVES shift(1).
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import (  # noqa: E402
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    fill_allowed,
    regime_mask_from_btc,
    resample_1h,
    signal_bar_cap,
)

P = DEFAULT_PARAMS

COIL = (101.0, 103.0, 100.0, 101.5, 1000.0)
FIRE = (102.0, 103.8, 101.8, 103.5, 2500.0)


def make_df(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    df["date"] = pd.date_range("2024-11-01", periods=len(df), freq="15min", tz="UTC")
    return df


def golden():
    return make_df([COIL] * 60 + [FIRE])


def btc_trend(start, step, n=60):
    closes = [start + step * i for i in range(n)]
    return pd.DataFrame({"close": closes, "volume": [1000.0] * n})


# --- 1h resample (regime source; look-ahead-sensitive) --------------------

def test_resample_1h_uses_bucket_open_and_last_close():
    # A 1h bar labelled 10:00 must contain only 10:00..10:45 (close 4), never
    # 11:00's close (5) — otherwise the regime would peek ahead one hour.
    dates = pd.date_range("2026-02-01 10:00", periods=9, freq="15min", tz="UTC")
    out = resample_1h(pd.DataFrame({"date": dates, "close": [1.0, 2, 3, 4, 5, 6, 7, 8, 9]}))
    assert list(out["date"]) == [
        pd.Timestamp("2026-02-01 10:00", tz="UTC"),
        pd.Timestamp("2026-02-01 11:00", tz="UTC"),
        pd.Timestamp("2026-02-01 12:00", tz="UTC"),
    ]
    assert list(out["close"]) == [4.0, 8.0, 9.0]


# --- regime ---------------------------------------------------------------

def test_regime_true_in_clear_uptrend():
    regime = regime_mask_from_btc(btc_trend(100.0, 0.5), P)
    assert bool(regime.iloc[-1]) is True


def test_regime_false_in_clear_downtrend():
    regime = regime_mask_from_btc(btc_trend(130.0, -0.5), P)
    assert bool(regime.iloc[-1]) is False


# --- golden breakout + individual sub-gates -------------------------------

def test_golden_breakout_fires_and_all_subgates_pass():
    df = add_indicators(golden(), P)
    last = df.iloc[-1]
    # sub-gates asserted individually so a failure names the culprit
    assert last["range_high"] == 103.0
    assert last["range_low"] == 100.0
    assert last["range_width"] <= P["range_max_width"]
    assert last["close"] > last["range_high"]
    assert last["close"] <= last["entry_cap"]
    assert last["volume"] >= P["volume_mult"] * last["vol_avg"]
    mask = entry_mask(df, P, True)
    assert bool(mask.iloc[-1]) is True
    assert mask.sum() == 1  # coil bars and warmup never fire


def test_entry_cap_is_extension_above_range_high():
    df = add_indicators(golden(), P)
    assert df["entry_cap"].iloc[-1] == pytest.approx(103.0 * (1 + P["max_extension"]))


# --- negatives: one perturbed gate each -----------------------------------

def test_regime_false_blocks_perfect_breakout():
    df = add_indicators(golden(), P)
    assert entry_mask(df, P, False).sum() == 0


def test_wide_range_blocks_breakout():
    # Coil lows at 96.5 -> width (103-96.5)/96.5 = 6.7% > 6%: not a coil.
    wide_coil = (101.0, 103.0, 96.5, 101.5, 1000.0)
    df = add_indicators(make_df([wide_coil] * 60 + [FIRE]), P)
    assert df["range_width"].iloc[-1] > P["range_max_width"]
    assert entry_mask(df, P, True).sum() == 0


def test_close_below_range_high_is_not_a_breakout():
    no_break = (102.0, 103.8, 101.8, 102.8, 2500.0)  # close 102.8 <= 103
    df = add_indicators(make_df([COIL] * 60 + [no_break]), P)
    assert df["close"].iloc[-1] <= df["range_high"].iloc[-1]
    assert entry_mask(df, P, True).sum() == 0


def test_close_above_cap_is_a_chase_and_blocked():
    chase = (102.0, 104.8, 101.8, 104.6, 2500.0)  # 104.6 > 103*1.015 = 104.545
    df = add_indicators(make_df([COIL] * 60 + [chase]), P)
    last = df.iloc[-1]
    assert last["close"] > last["range_high"]      # it IS a breakout...
    assert last["close"] > last["entry_cap"]       # ...but an escaped train
    assert entry_mask(df, P, True).sum() == 0


def test_weak_volume_blocks_breakout():
    quiet = (102.0, 103.8, 101.8, 103.5, 1500.0)  # 1500 < 2 x ~1010
    df = add_indicators(make_df([COIL] * 60 + [quiet]), P)
    last = df.iloc[-1]
    assert last["volume"] < P["volume_mult"] * last["vol_avg"]
    assert entry_mask(df, P, True).sum() == 0


# --- look-ahead: the firing bar must be excluded from its own range --------

def test_firing_bar_own_high_excluded_from_range():
    spike = (102.0, 200.0, 101.8, 103.5, 2500.0)  # monster wick on the firing bar
    df = add_indicators(make_df([COIL] * 60 + [spike]), P)
    # If rolling included the current bar, range_high would be 200 and the
    # breakout (close > range_high) could never fire. shift(1) keeps it 103.
    assert df["range_high"].iloc[-1] == 103.0
    assert bool(entry_mask(df, P, True).iloc[-1]) is True


# --- regime passed as an aligned Series (the strategy's real path) ---------

def test_regime_series_true_on_firing_bar_fires():
    df = add_indicators(golden(), P)
    regime = pd.Series(True, index=df.index)
    assert bool(entry_mask(df, P, regime).iloc[-1]) is True


def test_regime_series_false_on_firing_bar_blocks():
    df = add_indicators(golden(), P)
    regime = pd.Series(True, index=df.index)
    regime.iloc[-1] = False
    assert bool(entry_mask(df, P, regime).iloc[-1]) is False


# --- warmup / dead market -------------------------------------------------

def test_flat_market_never_signals():
    flat = (100.0, 100.0, 100.0, 100.0, 1000.0)
    df = add_indicators(make_df([flat] * 80), P)
    assert entry_mask(df, P, True).sum() == 0


def test_warmup_rows_never_signal():
    df = add_indicators(make_df([COIL] * 10), P)
    assert entry_mask(df, P, True).sum() == 0


# --- fill veto: the cap is FROZEN at the signal bar (spec s3 auditor pin) ---

def test_signal_bar_cap_reads_the_signal_bars_cap():
    df = add_indicators(golden(), P)
    df["enter_long"] = entry_mask(df, P, True).astype(int)
    fill_time = df["date"].iloc[-1] + pd.Timedelta(minutes=15)
    assert signal_bar_cap(df, fill_time) == pytest.approx(103.0 * (1 + P["max_extension"]))


def test_signal_bar_cap_frozen_not_rolling():
    # Two bars AFTER the signal push the rolling range up to 110; the frozen
    # cap must still come from the signal bar. A rolling reference would
    # quietly re-admit the chase.
    later = (104.0, 110.0, 103.0, 108.0, 1000.0)
    df = add_indicators(make_df([COIL] * 60 + [FIRE] + [later] * 2), P)
    df["enter_long"] = entry_mask(df, P, True).astype(int)
    assert df["enter_long"].sum() == 1  # only the original breakout fired
    fill_time = df["date"].iloc[-1] + pd.Timedelta(minutes=15)
    cap = signal_bar_cap(df, fill_time)
    assert cap == pytest.approx(103.0 * (1 + P["max_extension"]))
    assert df["entry_cap"].iloc[-1] > cap  # the rolling cap moved on; the frozen one didn't


def test_signal_bar_cap_none_without_prior_signal():
    df = add_indicators(golden(), P)
    df["enter_long"] = 0
    assert signal_bar_cap(df, df["date"].iloc[-1] + pd.Timedelta(minutes=15)) is None


def test_signal_bar_cap_ignores_signal_at_or_after_fill_time():
    df = add_indicators(golden(), P)
    df["enter_long"] = entry_mask(df, P, True).astype(int)
    # fill_time == the signal bar itself: the signal is not strictly before it
    assert signal_bar_cap(df, df["date"].iloc[-1]) is None


def test_fill_allowed_at_cap_but_not_above():
    cap = 104.545
    assert fill_allowed(cap, cap) is True
    assert fill_allowed(cap * 1.0001, cap) is False
    assert fill_allowed(100.0, None) is False  # no cap -> fail closed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_momentum_signals.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'fill_allowed'` (old module has pullback code).

- [ ] **Step 3: Rewrite momentum_signals.py**

Replace `user_data/strategies/momentum_signals.py` entirely with:

```python
"""Pure-pandas family-A signal math for MemeMomentum: higher-TF uptrend regime
+ 15m range-coil breakout entry, anti-chase capped at signal AND fill.

Kept freqtrade-free so it can be unit tested locally and reused verbatim by
the strategy and verification scripts. Every number comes from
docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md.

Prior families are frozen falsified (v1 chase, v2 market pullback, b' limit
pullback — git history keeps their code). Do not reintroduce them here.
"""
import pandas as pd

DEFAULT_PARAMS = {
    # Regime, computed on a higher-TF (1h) series — longs only in an up market.
    "regime_ema_fast": 20,
    "regime_ema_slow": 50,
    # Range coil on the 15m entry stream: the PRIOR `range_lookback` candles,
    # current bar excluded via shift(1) — the breakout candle must never be
    # part of the range it breaks out of.
    "range_lookback": 48,       # 48 x 15m = 12h
    "range_max_width": 0.06,    # (high - low) / low of the range
    # Anti-chase: entry only within this fraction above the range high; also
    # the fill-veto cap, frozen at the signal bar (confirm_trade_entry).
    "max_extension": 0.015,
    # Breakout-candle volume vs its rolling baseline.
    "volume_window": 48,
    "volume_mult": 2.0,
}


def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Add the numeric columns the entry gates read. Backward-looking only:
    range_high/range_low are shift(1) so the firing candle is excluded from
    its own range."""
    df = df.copy()
    n = params["range_lookback"]
    df["range_high"] = df["high"].rolling(n).max().shift(1)
    df["range_low"] = df["low"].rolling(n).min().shift(1)
    df["range_width"] = (df["range_high"] - df["range_low"]) / df["range_low"]
    df["vol_avg"] = df["volume"].rolling(params["volume_window"]).mean()
    # Per-bar cap; the fill veto reads the SIGNAL bar's value, never a later
    # bar's — a rolling reference would re-admit the chase (spec s3 pin).
    df["entry_cap"] = df["range_high"] * (1.0 + params["max_extension"])
    return df


def resample_1h(df: pd.DataFrame) -> pd.DataFrame:
    """Resample a 15m close series to 1h buckets labelled by their OPEN time
    (closed='left'), so a 1h bar never contains a candle that closes after its
    own label. Feeds regime_mask_from_btc; the strategy then merges the result
    back with freqtrade's merge_informative_pair (which adds the safe offset)."""
    return (
        df[["date", "close"]]
        .set_index("date")
        .resample("1h", label="left", closed="left")
        .agg({"close": "last"})
        .dropna()
        .reset_index()
    )


def regime_mask_from_btc(btc_1h: pd.DataFrame, params: dict) -> pd.Series:
    """Up-regime when BTC 1h close is above EMA(slow) and EMA(fast) > EMA(slow)."""
    close = btc_1h["close"]
    ema_fast = close.ewm(span=params["regime_ema_fast"], adjust=False).mean()
    ema_slow = close.ewm(span=params["regime_ema_slow"], adjust=False).mean()
    return (close > ema_slow) & (ema_fast > ema_slow)


def entry_mask(df: pd.DataFrame, params: dict, regime_ok) -> pd.Series:
    """Breakout long: up regime + tight prior range + close above the range
    high but inside the anti-chase cap + expanded volume. `regime_ok` is a
    bool (broadcast) or a Series already aligned to `df` (as the strategy
    passes it after the informative merge)."""
    if isinstance(regime_ok, pd.Series):
        regime = regime_ok.reindex(df.index).fillna(False).astype(bool)
    else:
        regime = pd.Series(bool(regime_ok), index=df.index)

    range_ok = df["range_width"] <= params["range_max_width"]
    breakout = df["close"] > df["range_high"]
    capped = df["close"] <= df["entry_cap"]
    volume_ok = df["vol_avg"].notna() & (
        df["volume"] >= params["volume_mult"] * df["vol_avg"]
    )
    mask = regime & range_ok & breakout & capped & volume_ok
    return mask.fillna(False)


def signal_bar_cap(df: pd.DataFrame, fill_time) -> float | None:
    """Entry cap FROZEN at the newest signal bar strictly before `fill_time`.
    Returns None when no prior signal bar (or no finite cap) exists — the
    caller fails closed and vetoes."""
    if "enter_long" not in df.columns:
        return None
    prior = df[(df["enter_long"] == 1) & (df["date"] < fill_time)]
    if prior.empty:
        return None
    cap = prior["entry_cap"].iloc[-1]
    return None if pd.isna(cap) else float(cap)


def fill_allowed(fill_rate: float, cap: float | None) -> bool:
    """The fill-side anti-chase bound (spec s3/s7): no cap -> fail closed;
    above the frozen cap -> the gap-open is an accepted missed fill."""
    return cap is not None and fill_rate <= cap
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_momentum_signals.py -q`
Expected: 21 passed.

- [ ] **Step 5: Commit**

```bash
git add user_data/strategies/momentum_signals.py tests/test_momentum_signals.py
git commit -m "Rewrite signals for family A range breakout with TDD tests"
```

---

### Task 2: Strategy wiring + config

**Files:**
- Modify: `user_data/strategies/MemeMomentum.py` (full rewrite of the class body)
- Modify: `config-paper.json`

**Interfaces:**
- Consumes from Task 1: `DEFAULT_PARAMS`, `add_indicators`, `entry_mask`, `regime_mask_from_btc`, `resample_1h`, `signal_bar_cap`, `fill_allowed`.
- Produces (Task 4 parses these log lines from captured stdout — format is an interface):
  - `ENTRY-VETO pair=<pair> fill=<rate> cap=<cap|none> time=<ts>`
  - `STAKE-SKIP pair=<pair> stake=<amt> min=<amt> time=<ts>`
- Strategy behavior relied on later: market entries, `confirm_trade_entry` veto, `custom_stake_amount` = 10% of `self.wallets.get_total_stake_amount()`, `stagnation_hours = None` (class attr; dev knob values 4/8/12).

- [ ] **Step 1: Rewrite MemeMomentum.py**

Replace `user_data/strategies/MemeMomentum.py` entirely with:

```python
import logging
from datetime import timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair

from momentum_signals import (
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    fill_allowed,
    regime_mask_from_btc,
    resample_1h,
    signal_bar_cap,
)

logger = logging.getLogger(__name__)


class MemeMomentum(IStrategy):
    """Family A (2026-07-20): long-only 15m range-coil breakout in a BTC
    up-regime. Spec: docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md.

    Entry = up regime (BTC 1h trend, fail-closed) + tight 12h range + close
    above the range high on 2x volume, never more than 1.5% above the range
    high — enforced twice: at the signal (entry_mask) and AT THE FILL
    (confirm_trade_entry vetoes any fill above the signal bar's frozen
    entry_cap; a candle can close inside the cap and gap open above it, and
    buying that gap would be v1 in disguise). Entries are market orders.

    Exits: -4% stop, late-peak ROI ladder 5/3/1.5%, tight trailing lock after
    +3%. NO stagnation exit by default (Austin's gate amendment — timed cuts
    are dev knobs; hold/slot diagnostics are mandatory instead).

    Sizing (Austin's gate amendment): 10% of current total equity per trade,
    max 10 open; below a pair's minimum -> skip and log.

    Regime source: only 15m BTC/USD data exists, so the 1h regime is
    resampled from it and merged back with merge_informative_pair (which adds
    the +45m offset that prevents look-ahead). Missing BTC data -> regime
    fails closed -> no entries. Protections implement master spec s6 and are
    never weakened (s8.5).
    """

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False
    process_only_new_candles = True
    # 600 x 15m = 6.25 days -> ~150 1h candles, enough for a converged 1h EMA50.
    startup_candle_count = 600

    params = DEFAULT_PARAMS
    btc_pair = "BTC/USD"
    regime_timeframe = "1h"

    # Sizing: fraction of current total equity per trade.
    stake_fraction = 0.10

    # Exits (spec s3): winners in this market peak late.
    minimal_roi = {"0": 0.05, "240": 0.03, "480": 0.015}
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.012
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    # Stagnation exit OFF by default (Austin's gate amendment). Dev knob
    # values: 4, 8, 12 (hours). None = no timed exit.
    stagnation_hours = None

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

    def informative_pairs(self):
        # BTC is loaded for the regime even though it need not be tradeable.
        return [(self.btc_pair, self.timeframe)]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = add_indicators(dataframe, self.params)

        # Regime from BTC: 15m -> 1h -> EMA trend -> merged back without peeking.
        if self.dp is None:
            dataframe["regime_ok"] = False
            return dataframe
        btc = self.dp.get_pair_dataframe(self.btc_pair, self.timeframe)
        if btc is None or len(btc) == 0:
            dataframe["regime_ok"] = False
            return dataframe
        btc_1h = resample_1h(btc)
        btc_1h["regime_ok"] = regime_mask_from_btc(btc_1h, self.params)
        dataframe = merge_informative_pair(
            dataframe,
            btc_1h[["date", "regime_ok"]],
            self.timeframe,
            self.regime_timeframe,
            ffill=True,
        )
        dataframe["regime_ok"] = (
            dataframe["regime_ok_1h"].fillna(False).astype(bool)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            entry_mask(dataframe, self.params, dataframe["regime_ok"]), "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe  # exits handled by ROI/stoploss/trailing (+ dev knob)

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time,
                            entry_tag, side: str, **kwargs) -> bool:
        """Anti-chase cap enforced AT THE FILL (spec s3): veto any fill above
        the SIGNAL bar's frozen entry_cap. Fails closed when the signal bar
        cannot be found. Every veto is logged for the dev diagnostics."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        cap = None
        if df is not None and len(df):
            cap = signal_bar_cap(df, current_time)
        if not fill_allowed(rate, cap):
            logger.info(
                "ENTRY-VETO pair=%s fill=%.10g cap=%s time=%s",
                pair, rate, "none" if cap is None else f"{cap:.10g}", current_time,
            )
            return False
        return True

    def custom_stake_amount(self, pair: str, current_time, current_rate: float,
                            proposed_stake: float, min_stake, max_stake: float,
                            leverage: float, entry_tag, side: str,
                            **kwargs) -> float:
        """10% of current total equity per trade (spec s3 sizing amendment).
        Below the pair minimum -> skip the entry (return 0) and log it, so
        freqtrade never silently bumps a small stake up to the minimum."""
        stake = self.wallets.get_total_stake_amount() * self.stake_fraction
        if min_stake is not None and stake < min_stake:
            logger.info("STAKE-SKIP pair=%s stake=%.2f min=%.2f time=%s",
                        pair, stake, min_stake, current_time)
            return 0
        return min(stake, max_stake)

    def custom_exit(self, pair: str, trade: Trade, current_time,
                    current_rate: float, current_profit: float, **kwargs):
        if self.stagnation_hours is None:  # default: off (gate amendment)
            return None
        if (current_time - trade.open_date_utc) > timedelta(hours=self.stagnation_hours) \
                and current_profit < 0.01:
            return "stagnation_timeout"
        return None
```

- [ ] **Step 2: Update config-paper.json**

Three edits (leave everything else untouched):
1. `"max_open_trades": 3` → `"max_open_trades": 10`
2. `"stake_amount": 250` → `"stake_amount": "unlimited"` (custom_stake_amount overrides per trade; unlimited keeps freqtrade's own proposal sane)
3. `"unfilledtimeout": {"entry": 240, ...}` → `"unfilledtimeout": {"entry": 10, "exit": 10, "unit": "minutes"}` (market entries; b′'s 4h resting window is gone)
4. Remove the line `"custom_price_max_distance_ratio": 0.05,` (b′-only knob; no custom_entry_price remains)

- [ ] **Step 3: Run the full suite (regression check)**

Run: `.venv/bin/pytest tests/ -q`
Expected: all pass (21 signal + 6 ranking). The strategy file has no direct unit tests — its pure logic lives in momentum_signals; integration is verified by the Task 5 smoke via `verify_breakout_cap.py`.

- [ ] **Step 4: Sanity-compile the strategy inside Docker**

Run: `docker compose run --rm freqtrade list-strategies --config /freqtrade/config-paper.json 2>&1 | tail -5`
Expected: `MemeMomentum` listed with status OK (proves imports/syntax inside the freqtrade image). If the config path differs in docker-compose volumes, use the mounted path shown in `docker-compose.yml`.

- [ ] **Step 5: Commit**

```bash
git add user_data/strategies/MemeMomentum.py config-paper.json
git commit -m "Wire family A into strategy: fill veto, 10% equity sizing, late-peak exits"
```

---

### Task 3: Arm-D ranking mode + per-arm fees + log capture (harness)

**Files:**
- Modify: `scripts/rolling_backtest.py`
- Modify: `tests/test_rolling_ranking.py` (append; existing tests unchanged)

**Interfaces:**
- Produces (Tasks 5/7 rely on):
  - CLI: `python3 scripts/rolling_backtest.py <start> <end> --arm {L,D}`
  - `rank_pairs_for_month(data_dir, month_start, top_n)` — unchanged signature/behavior (arm L)
  - `rank_pairs_downcap_for_month(data_dir, month_start) -> list[str]` (arm D)
  - `ARM_FEES = {"L": 0.0045, "D": 0.006}`
  - `run_month(month_start, pairs, fee)` saves captured stdout+stderr to `user_data/backtest_results/<result-stem>.log` (Task 4 parses ENTRY-VETO/STAKE-SKIP from it)
  - Summary files per arm: `rolling_summary_L.{json,md}` / `rolling_summary_D.{json,md}`

- [ ] **Step 1: Write the failing arm-D tests**

Append to `tests/test_rolling_ranking.py`:

```python
# --- family A arm D: rank-slice 31..100 FIRST, then the $100k/day floor -----

from rolling_backtest import ARM_FEES, rank_pairs_downcap_for_month


def _write_sized_feather(tmp_path, pair, month, price, volume, periods):
    dates = pd.date_range(month, periods=periods, freq="15min", tz="UTC")
    df = pd.DataFrame({
        "date": dates, "open": price, "high": price, "low": price,
        "close": price, "volume": volume,
    })
    df.to_feather(tmp_path / f"{pair}-15m.feather")


def test_arm_fees_match_spec():
    assert ARM_FEES == {"L": 0.0045, "D": 0.006}


def test_downcap_excludes_top_30_and_keeps_the_band(tmp_path):
    # 32 pairs, strictly descending volume, all far above the $100k/day floor.
    # Ranks 1..30 are excluded; ranks 31..32 are the arm-D universe.
    for i in range(32):
        _write_sized_feather(tmp_path, f"P{i:02d}_USD", "2026-06-01",
                             price=2.0, volume=10000.0 - 100 * i, periods=2000)
    ranked = rank_pairs_downcap_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"))
    assert ranked == ["P30/USD", "P31/USD"]


def test_downcap_floor_drops_thin_band_member(tmp_path):
    # Rank 32's volume sits under $100k/day -> dropped AFTER slicing.
    for i in range(31):
        _write_sized_feather(tmp_path, f"P{i:02d}_USD", "2026-06-01",
                             price=2.0, volume=10000.0 - 100 * i, periods=2000)
    _write_sized_feather(tmp_path, "THIN_USD", "2026-06-01",
                         price=1.0, volume=500.0, periods=2000)  # $48k/day
    ranked = rank_pairs_downcap_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"))
    assert ranked == ["P30/USD"]


def test_downcap_ranks_full_set_before_floor(tmp_path):
    # The distinguishing test for the auditor-pinned ORDER of operations:
    # a sub-floor pair must still OCCUPY its rank slot. PX ranks 5th by total
    # quote volume but averages under $100k/day (full month of thin days).
    # Rank-then-floor: 31 ranked pairs -> band = [rank 31] -> [P26].
    # Floor-then-rank (the bug) would remove PX first, leaving 30 pairs and
    # an EMPTY band. 2880 candles = all 30 days of June.
    for i in range(4):   # ranks 1-4: huge volume, 10 trading days
        _write_sized_feather(tmp_path, f"BIG{i}_USD", "2026-06-01",
                             price=100.0, volume=50000.0 - 100 * i, periods=960)
    _write_sized_feather(tmp_path, "PX_USD", "2026-06-01",  # rank 5: qv $2.9M, adv ~$96.7k
                         price=1.0, volume=2_900_000.0 / 2880, periods=2880)
    for i in range(26):  # ranks 6-31: 10 days, adv = qv/10 well above floor
        _write_sized_feather(tmp_path, f"P{i:02d}_USD", "2026-06-01",
                             price=1.0, volume=(2_800_000.0 - 20_000 * i) / 960,
                             periods=960)
    ranked = rank_pairs_downcap_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"))
    assert ranked == ["P25/USD"]  # the lowest-qv pair = rank 31, adv ~$254k/day
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_rolling_ranking.py -x -q`
Expected: FAIL — `ImportError: cannot import name 'ARM_FEES'`.

- [ ] **Step 3: Modify rolling_backtest.py**

Changes, keeping the file's structure:

1. Update the docstring's usage line to `Usage: python3 scripts/rolling_backtest.py 2024-02 2025-08 --arm L` and add one arm-description sentence.
2. Add `import argparse` and near the constants:

```python
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
```

3. Extract the shared per-pair volume collector and re-express arm L with it (behavior identical — existing tests must stay green); add the arm-D path:

```python
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
```

(The old inline body of `rank_pairs_for_month` is replaced by the two-liner above; `pd.read_feather(..., columns=...)` also cuts 18-month ranking IO.)

4. `run_month` gains a `fee` parameter and saves the captured output (the `--fee` argument uses it; delete the module-level `FEE = 0.004` and fix the summary text to reference the arm fee):

```python
def run_month(month_start: pd.Timestamp, pairs: list[str], fee: float) -> dict | None:
```

... `"--fee", str(fee),` in the subprocess command, and right after the zip-exists wait succeeds:

```python
    # Keep this run's full output: the dev diagnostics count ENTRY-VETO /
    # STAKE-SKIP lines from it (strategy logger -> stdout).
    (RESULTS_DIR / (result_file.stem + ".log")).write_text(out.stdout + out.stderr)
```

5. `main()` becomes argparse-driven; the ranking function and fee follow the arm; summary filenames carry the arm:

```python
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
```

...aggregation unchanged, plus `"arm": args.arm, "fee": fee` in the summary dict, and the two output files renamed `rolling_summary_{args.arm}.json` / `rolling_summary_{args.arm}.md` (the md title line says which arm and fee).

- [ ] **Step 4: Run the ranking tests**

Run: `.venv/bin/pytest tests/test_rolling_ranking.py -q`
Expected: 10 passed (6 old arm-L/parser tests untouched and green + 4 new).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest tests/ -q`
Expected: 31 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/rolling_backtest.py tests/test_rolling_ranking.py
git commit -m "Add arm D down-cap ranking mode, per-arm fees, and per-run log capture"
```

---

### Task 4: Diagnostics + breakout-cap verifier

**Files:**
- Create: `scripts/verify_breakout_cap.py`
- Create: `scripts/run_diagnostics.py`
- Create: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: result zips (freqtrade trade json inside), `.log` files from Task 3, log-line formats from Task 2, `DEFAULT_PARAMS`/`add_indicators` from Task 1.
- Produces:
  - `verify_breakout_cap.py zip [zip...]` — exit 1 on any bound violation
  - `run_diagnostics.py zip [zip...]` — human report + one ready-to-paste DEV markdown row
  - Pure functions under test: `count_vetoes(text)`, `count_stake_skips(text)`, `slot_occupancy(trades, max_slots)`, `hold_stats(trades)`

- [ ] **Step 1: Write failing tests for the pure diagnostic functions**

Create `tests/test_diagnostics.py`:

```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from run_diagnostics import count_stake_skips, count_vetoes, hold_stats, slot_occupancy


LOG = """\
2024-11-03 04:15:00 - MemeMomentum - INFO - ENTRY-VETO pair=WIF/USD fill=2.31 cap=2.29 time=2024-11-03 04:15:00+00:00
2024-11-03 04:15:01 - freqtrade.worker - INFO - something else entirely
2024-11-04 09:30:00 - MemeMomentum - INFO - ENTRY-VETO pair=PEPE/USD fill=1.1e-05 cap=1.09e-05 time=2024-11-04 09:30:00+00:00
2024-11-05 10:00:00 - MemeMomentum - INFO - STAKE-SKIP pair=XCN/USD stake=0.75 min=1.00 time=2024-11-05 10:00:00+00:00
"""


def test_count_vetoes_finds_only_veto_lines():
    assert count_vetoes(LOG) == 2
    assert count_vetoes("") == 0


def test_count_stake_skips():
    assert count_stake_skips(LOG) == 1


def _trade(open_date, close_date, duration_min):
    return {"open_date": open_date, "close_date": close_date,
            "trade_duration": duration_min}


def test_slot_occupancy_overlapping_trades():
    # [0h,2h] and [1h,3h]: span 3h -> 1 slot for 2h, 2 slots for 1h.
    trades = [
        _trade("2024-11-01 00:00:00+00:00", "2024-11-01 02:00:00+00:00", 120),
        _trade("2024-11-01 01:00:00+00:00", "2024-11-01 03:00:00+00:00", 120),
    ]
    occ = slot_occupancy(trades, max_slots=2)
    assert occ["max_concurrent"] == 2
    assert occ["mean_concurrent"] == pytest.approx(4 / 3)
    assert occ["frac_time_full"] == pytest.approx(1 / 3)


def test_slot_occupancy_disjoint_trades_never_full():
    trades = [
        _trade("2024-11-01 00:00:00+00:00", "2024-11-01 01:00:00+00:00", 60),
        _trade("2024-11-01 02:00:00+00:00", "2024-11-01 03:00:00+00:00", 60),
    ]
    occ = slot_occupancy(trades, max_slots=10)
    assert occ["max_concurrent"] == 1
    assert occ["frac_time_full"] == 0.0


def test_hold_stats_from_trade_durations():
    trades = [_trade("x", "y", 60), _trade("x", "y", 120), _trade("x", "y", 480)]
    hs = hold_stats(trades)
    assert hs["median_h"] == pytest.approx(2.0)
    assert hs["max_h"] == pytest.approx(8.0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_diagnostics.py -x -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'run_diagnostics'`.

- [ ] **Step 3: Write run_diagnostics.py**

Create `scripts/run_diagnostics.py`:

```python
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
```

- [ ] **Step 4: Run the diagnostic tests**

Run: `.venv/bin/pytest tests/test_diagnostics.py -q`
Expected: 5 passed.

- [ ] **Step 5: Write verify_breakout_cap.py**

Create `scripts/verify_breakout_cap.py`:

```python
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


def candles(pair: str) -> pd.DataFrame:
    if pair not in _cache:
        df = pd.read_feather(DATA / f"{pair.replace('/', '_')}-15m.feather")
        df["date"] = pd.to_datetime(df["date"], utc=True)
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
```

- [ ] **Step 6: Full suite green**

Run: `.venv/bin/pytest tests/ -q`
Expected: 36 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/verify_breakout_cap.py scripts/run_diagnostics.py tests/test_diagnostics.py
git commit -m "Add family A run diagnostics and breakout-cap verifier"
```

---

### Task 5: Smoke run — 2024-11, both arms

**Files:** none created (results land in gitignored `user_data/backtest_results/`); fixes to earlier files if the smoke exposes bugs.

**Interfaces:**
- Consumes: everything above. 2024-11 is a high up-regime dev month (universe_depth survey).

- [ ] **Step 1: Arm L smoke**

Run: `.venv/bin/python3 scripts/rolling_backtest.py 2024-11 2024-11 --arm L`
Expected: one month backtested at fee 0.0045, a `backtest-result-*.zip` + `.log` in `user_data/backtest_results/`, inline month line with trades/profit. Note the zip name.

- [ ] **Step 2: Arm D smoke**

Run: `.venv/bin/python3 scripts/rolling_backtest.py 2024-11 2024-11 --arm D`
Expected: 41–70 pairs, fee 0.006, its own zip + log.

- [ ] **Step 3: Verify the cap on every fill (both bounds)**

Run: `.venv/bin/python3 scripts/verify_breakout_cap.py user_data/backtest_results/<L-zip> user_data/backtest_results/<D-zip>`
Expected: `All fills obey the signal-bar-frozen anti-chase cap (both bounds).` — exit 0.

- [ ] **Step 4: Verify regime gating**

Run: `.venv/bin/python3 scripts/verify_regime_gating.py user_data/backtest_results/<L-zip> user_data/backtest_results/<D-zip>`
Expected: `All trades opened in up-regime`.

- [ ] **Step 5: Diagnostics + stake check**

Run: `.venv/bin/python3 scripts/run_diagnostics.py user_data/backtest_results/<L-zip>` (and the D zip)
Expected: veto/skip counts, hold and slot stats print. Then confirm sizing — stakes ≈10% of running equity (first trade ≈ $75 on a $750 wallet):

```bash
.venv/bin/python3 - <<'EOF'
import json, zipfile, sys
zp = "user_data/backtest_results/<L-zip>"
with zipfile.ZipFile(zp) as z:
    inner = [n for n in z.namelist() if n.endswith(".json")
             and not n.endswith("_config.json") and not n.endswith(".meta.json")]
    trades = json.loads(z.read(inner[0]))["strategy"]["MemeMomentum"]["trades"]
for t in trades[:5]:
    print(t["open_date"], round(t["stake_amount"], 2))
EOF
```

Expected: first stake ≈ 75.0; later stakes drift with equity, all near 10%.

- [ ] **Step 6: Zero-trade guard**

If BOTH arms produced zero trades in this high up-regime month, stop and debug before proceeding (signal counts per gate, e.g. adapt `scripts/count_signals.py`) — do not continue to the baseline with a possibly-dead signal path.

- [ ] **Step 7: Full suite green, then commit any smoke-driven fixes**

Run: `.venv/bin/pytest tests/ -q`
Expected: 36 passed.

```bash
git add -A && git commit -m "Smoke-test family A on 2024-11, both arms" --allow-empty
```

(If the smoke required code fixes, the commit carries them; otherwise it records the checkpoint.)

---

### Task 6: Pre-dev survivorship check (web research)

**Files:**
- Modify: `docs/backtests.md` (append a section)

**Interfaces:**
- Consumes: WebSearch/WebFetch for Kraken delisting notices 2024–2026; universe sizes from the spec (arm L 43–124, arm D 41–70 pairs/month).

- [ ] **Step 1: Research Kraken delistings**

Web-search (multiple queries): `Kraken delisting 2024 site:blog.kraken.com`, `Kraken "will be delisted" USD pairs 2025`, `Kraken asset removal support 2026`, etc. Fetch the concrete notices. Compile: asset, USD pair (if quoted in USD), announced delist date.

- [ ] **Step 2: Count against the windows**

Count delisted USD pairs whose delist date falls after 2024-01 (so they traded during dev/holdout but are missing from today's feathers). Compare against per-month universe sizes (arm L floor population 43–124; arm D band 41–70).

- [ ] **Step 3: Record in docs/backtests.md**

Append a section `## Family A pre-dev survivorship check — 2026-07-20` with: the notice list (asset, date, source URL), the counts, and the honest conclusion sentence — how big the survivor hole is, which arm it likely flatters more, and that this hardens skepticism on any later dev/holdout "pass" (spec §5). If public notices are sparse/incomplete, say so plainly — a lower bound is still a bound.

- [ ] **Step 4: Commit**

```bash
git add docs/backtests.md
git commit -m "Record pre-dev Kraken delisting survivorship check"
```

---

### Task 7: Dev baseline — iteration 1 of ≤15

**Files:**
- Modify: `docs/backtests.md` (append the DEV table with the baseline rows)

**Interfaces:**
- Consumes: harness `--arm L|D`, diagnostics, verifiers. Window: 2024-02→2025-08 (18 months; ranking months 2024-01→2025-07).

- [ ] **Step 1: Log the hypothesis BEFORE the run**

Append to `docs/backtests.md`:

```markdown
## Family A DEV phase — spec 2026-07-20-yolo-family-a-range-breakout.md §5

Window 2024-02→2025-08. Hard budget 15 iterations; one knob per iteration,
hypothesis logged BEFORE each run. Fees: arm L 0.0045, arm D 0.006. Holdout
2025-09→2026-01 SEALED. Stagnation exit off (Austin's amendment); hold/slot
diagnostics mandatory.

| Iter | Date | Knob (vs best) | Hypothesis (pre-run) | Arm | Trades | Profit % | Worst mo DD % | Tr/up-wk | Vetoes | Med hold h | Max slots | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-07-20 | — (spec defaults) | Baseline: breakout-at-start placement clears fees in up-regime where pullback entries could not | L | | | | | | | | |
| 1 | 2026-07-20 | — (spec defaults) | same | D | | | | | | | | |
```

- [ ] **Step 2: Run arm L**

Run: `.venv/bin/python3 scripts/rolling_backtest.py 2024-02 2025-08 --arm L`
Expected: 18 monthly lines + `rolling_summary_L.json/md` (~2–4 minutes).

- [ ] **Step 3: Run arm D**

Run: `.venv/bin/python3 scripts/rolling_backtest.py 2024-02 2025-08 --arm D`

- [ ] **Step 4: Verify mechanics on the full baseline**

Run `verify_breakout_cap.py` and `verify_regime_gating.py` over all 36 zips (glob the run timestamps from the two summaries' month lines), and `run_diagnostics.py` per arm (18 zips each). Expected: zero cap violations, zero out-of-regime entries.

- [ ] **Step 5: Fill the DEV rows + diagnostics**

Complete the two iteration-1 rows in `docs/backtests.md` from the summaries and diagnostics (trades, profit, worst monthly DD, trades/up-week, vetoes, median hold, max slots). Add 3–5 sentences: per-month spread, exit-reason mix, veto count and whether vetoed entries clustered anywhere, slot pressure.

- [ ] **Step 6: Commit + push**

```bash
git add docs/backtests.md
git commit -m "Run family A dev baseline (iteration 1) on both arms"
git push
```

- [ ] **Step 7: Report to Austin and STOP**

Report: baseline numbers per arm, mechanics-verification results, survivorship-check summary, and the FIRST one-knob hypothesis proposal (chosen from the spec §3 grids based on what the baseline diagnostics show). Do not run iteration 2 without his go.

---

## Self-Review (done at write time)

- **Spec coverage:** §3 entry table → Task 1; fill veto + frozen cap → Tasks 1–2; market entries + timeout → Task 2; sizing amendment → Task 2; exits + stagnation-off → Task 2; protections untouched → Task 2 (verbatim copy); §4 arms/fees/auditor pin → Task 3; §3 veto diagnostics + Austin's hold/slot mandate → Task 4; smoke → Task 5; §5 pre-dev check → Task 6; §5 dev baseline + one-knob logging → Task 7. Holdout/kill windows: never touched (global constraint).
- **Placeholders:** none — every code step is complete code; Task 6 is research prose by nature.
- **Type consistency:** `signal_bar_cap(df, fill_time)`, `fill_allowed(rate, cap)`, `rank_pairs_downcap_for_month(data_dir, month_start)`, `run_month(month_start, pairs, fee)`, log-line formats — checked consistent across Tasks 1–5.
- **Known judgment calls (recorded):** range uses the OHLC `high`/`low` columns (the natural reading of "rolling high/low" for a coil; v2's closes-based rule was pullback-specific). `vol_avg` includes the current bar (spec says plain "rolling mean"; at window 48 the difference is ≤2% of the threshold, and including it is strictly stricter). Freqtrade truncates `get_analyzed_dataframe` to the current candle in backtests, and `signal_bar_cap` filters `date < fill_time` anyway — belt and braces.
