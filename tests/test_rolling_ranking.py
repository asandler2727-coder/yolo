import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from rolling_backtest import rank_pairs_for_month, result_file_from_output


def test_result_file_taken_from_this_runs_stdout(tmp_path):
    # freqtrade prints the exact file it wrote; parsing that (not the shared
    # .last_result.json pointer) is race-free and immune to bind-mount lag.
    out = (
        "INFO - Backtesting with data ...\n"
        'freqtrade.misc - INFO - dumping json to '
        '"/freqtrade/user_data/backtest_results/backtest-result-2026-07-19_07-51-03.meta.json"\n'
        "Result for strategy MemeMomentum\n"
    )
    assert result_file_from_output(out, tmp_path) == (
        tmp_path / "backtest-result-2026-07-19_07-51-03.zip"
    )


def test_result_file_uses_last_dump_when_several(tmp_path):
    out = (
        'dumping json to "/x/backtest-result-2026-07-19_01-00-00.meta.json"\n'
        'dumping json to "/x/backtest-result-2026-07-19_02-00-00.meta.json"\n'
    )
    assert result_file_from_output(out, tmp_path) == (
        tmp_path / "backtest-result-2026-07-19_02-00-00.zip"
    )


def test_result_file_none_when_no_dump_line(tmp_path):
    assert result_file_from_output("no result written", tmp_path) is None


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
    # Both pairs clear the $250k/day floor: 96 candles/day x price x volume.
    _write_feather(tmp_path, "BIG_USD", "2026-06-01", price=2.0, volume=5000.0)   # $960k/day
    _write_feather(tmp_path, "SMALL_USD", "2026-06-01", price=1.0, volume=3000.0)  # $288k/day
    ranked = rank_pairs_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"), top_n=1)
    assert ranked == ["BIG/USD"]


def test_pair_with_no_prior_data_is_excluded(tmp_path):
    # Data starts in July; for July's ranking (prior month = June) it must not appear.
    _write_feather(tmp_path, "NEW_USD", "2026-07-01", price=1.0, volume=100000.0)
    ranked = rank_pairs_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"), top_n=5)
    assert ranked == []


def test_pair_below_live_volume_floor_is_excluded(tmp_path):
    # Mirrors the live VolumePairList min_value: a pair averaging under
    # $250k/day quote volume in the prior month must never enter the backtest
    # universe, even when top_n has room for it.
    _write_feather(tmp_path, "LIQUID_USD", "2026-06-01", price=2.0, volume=5000.0)  # $960k/day
    _write_feather(tmp_path, "THIN_USD", "2026-06-01", price=1.0, volume=100.0)     # $9.6k/day
    ranked = rank_pairs_for_month(tmp_path, pd.Timestamp("2026-07-01", tz="UTC"), top_n=5)
    assert ranked == ["LIQUID/USD"]


# --- family A arm D: rank-slice 31..100 FIRST, then the $100k/day floor -----

from rolling_backtest import ARM_FEES, rank_pairs_downcap_for_month  # noqa: E402


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
    # Rank-then-floor: 31 ranked pairs -> band = [rank 31] -> [P25].
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
