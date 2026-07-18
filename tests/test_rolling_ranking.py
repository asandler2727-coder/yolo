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
