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


def test_slot_occupancy_close_and_open_on_same_candle_do_not_stack():
    # Freqtrade processes exits before entries within a candle: a trade
    # closing at 01:00 frees its slot for one opening at 01:00. Counting the
    # open first would report phantom concurrency above max_open_trades.
    trades = [
        _trade("2024-11-01 00:00:00+00:00", "2024-11-01 01:00:00+00:00", 60),
        _trade("2024-11-01 01:00:00+00:00", "2024-11-01 02:00:00+00:00", 60),
    ]
    occ = slot_occupancy(trades, max_slots=2)
    assert occ["max_concurrent"] == 1
    assert occ["frac_time_full"] == 0.0


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
