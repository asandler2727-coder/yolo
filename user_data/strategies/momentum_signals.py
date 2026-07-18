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
