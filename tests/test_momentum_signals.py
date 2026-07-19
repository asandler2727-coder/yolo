"""v2 pullback-in-uptrend signal tests.

Design: one GOLDEN entry fixture (regime up + prior impulse + pullback into band
+ volume alive + close above pair EMA). Every negative is the golden fixture
with exactly ONE gate perturbed, so a red test names the gate that broke.

Fixture geometry notes:
- "the high" in the pullback rule = highest *close* over impulse_lookback,
  matching the impulse rule (not the OHLC `high` column).
- The impulse peak sits several bars before the firing bar so the last 3 bars
  are all on the declining side; otherwise the anti-chase gate (pct_change over
  3 bars < 2%) would fight a valid pullback and block the entry we want to fire.
- 58 flat low bars precede the impulse so EMA50 lags well below the pullback
  close and `require_pair_above_ema` passes on the golden bar.
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "user_data" / "strategies"))
from momentum_signals import (  # noqa: E402
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    regime_mask_from_btc,
)

P = DEFAULT_PARAMS


def make_df(closes, volumes):
    return pd.DataFrame({"close": closes, "volume": volumes})


# --- fixtures -------------------------------------------------------------

def golden():
    # 58 flat bars, then impulse to a peak at idx 63 (+~5%), then a 6-bar
    # pullback ending ~1.9% below the peak on the firing bar (idx 69).
    closes = [100.0] * 58 + [
        101.0, 102.5, 104.0, 105.0, 105.5, 106.0,  # rise, peak = 106 @ idx63
        105.5, 105.0, 104.6, 104.3, 104.1, 104.0,  # pullback to 104.0 @ idx69
    ]
    volumes = [1000.0] * 58 + [2500.0] * 12  # volume alive on the move
    return make_df(closes, volumes)


def collapse():
    # Golden, but the firing bar falls to 100.5 -> ~5.2% below the 106 high,
    # past pullback_max_pct: a full trend failure, not a pullback.
    df = golden()
    df.loc[df.index[-1], "close"] = 100.5
    return df


def chase():
    # Everything passes EXCEPT anti-chase: a dip at idx66 (t-3) then a fresh
    # peak at idx67 (t-2) makes the 3-bar change to the firing bar ~+2.2% (>=2%),
    # while the firing close is still ~1.7% below that fresh high (valid pullback).
    closes = [100.0] * 58 + [
        101.0, 102.0, 103.0, 104.0, 105.0, 105.5,
        105.0, 104.0, 102.0, 106.0, 105.0, 104.2,  # dip 102 @66, peak 106 @67
    ]
    volumes = [1000.0] * 58 + [2500.0] * 12
    return make_df(closes, volumes)


def btc_trend(start, step, n=60):
    closes = [start + step * i for i in range(n)]
    return pd.DataFrame({"close": closes, "volume": [1000.0] * n})


# --- regime ---------------------------------------------------------------

def test_regime_true_in_clear_uptrend():
    regime = regime_mask_from_btc(btc_trend(100.0, 0.5), P)
    assert bool(regime.iloc[-1]) is True


def test_regime_false_in_clear_downtrend():
    regime = regime_mask_from_btc(btc_trend(130.0, -0.5), P)
    assert bool(regime.iloc[-1]) is False


# --- golden entry + individual sub-gates ----------------------------------

def test_golden_pullback_fires_and_all_subgates_pass():
    df = add_indicators(golden(), P)
    last = df.iloc[-1]
    # sub-gates asserted individually so a failure names the culprit
    assert last["impulse_pct"] >= P["impulse_min_pct"]
    assert P["pullback_min_pct"] <= last["drawdown_from_high"] <= P["pullback_max_pct"]
    assert last["volume"] >= P["volume_mult"] * last["vol_avg"]
    assert last["pct_change_3"] < P["chase_block_pct"]
    assert last["close"] > last["ema_pair"]
    assert bool(entry_mask(df, P, True).iloc[-1]) is True


# --- negatives: one perturbed gate each -----------------------------------

def test_regime_false_blocks_perfect_pullback():
    df = add_indicators(golden(), P)
    assert entry_mask(df, P, False).sum() == 0


def test_chase_block_stops_hot_last_three_bars():
    df = add_indicators(chase(), P)
    last = df.iloc[-1]
    # pullback geometry still valid, but the 3-bar move is too hot
    assert P["pullback_min_pct"] <= last["drawdown_from_high"] <= P["pullback_max_pct"]
    assert last["pct_change_3"] >= P["chase_block_pct"]
    assert bool(entry_mask(df, P, True).iloc[-1]) is False


def test_full_collapse_past_max_pullback_does_not_signal():
    df = add_indicators(collapse(), P)
    assert df.iloc[-1]["drawdown_from_high"] > P["pullback_max_pct"]
    assert bool(entry_mask(df, P, True).iloc[-1]) is False


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
    df = add_indicators(make_df([100.0] * 80, [1000.0] * 80), P)
    assert entry_mask(df, P, True).sum() == 0


def test_warmup_rows_never_signal():
    df = add_indicators(make_df([100.0] * 10, [1000.0] * 10), P)
    assert entry_mask(df, P, True).sum() == 0
