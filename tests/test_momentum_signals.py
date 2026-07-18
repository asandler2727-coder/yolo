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
