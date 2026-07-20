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
