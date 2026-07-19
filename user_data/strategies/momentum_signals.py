"""Pure-pandas v2 signal math for MemeMomentum: higher-TF uptrend regime +
15m pullback-into-support entry (non-chase), fee-aware by design.

Kept freqtrade-free so it can be unit tested locally and reused verbatim by the
strategy and backtest harness. See
docs/superpowers/specs/2026-07-19-yolo-v2-pullback-redesign.md for the math.

v1 (chase a completed pump + climax volume) is frozen — proven negative
expectancy at taker fees. Do not reintroduce it here.
"""
import pandas as pd

DEFAULT_PARAMS = {
    # Regime, computed on a higher-TF (1h) series — longs only in an up market.
    "regime_ema_fast": 20,
    "regime_ema_slow": 50,
    # Impulse + pullback geometry on the 15m entry stream.
    "impulse_lookback": 12,      # 12 x 15m = 3h window for the prior move
    "impulse_min_pct": 0.04,     # the window must have advanced >= 4%
    "pullback_min_pct": 0.015,   # firing close >= 1.5% below the window high
    "pullback_max_pct": 0.05,    # ...but <= 5% below it (else trend failure)
    # Anti-chase: block if the last 3 bars already ripped.
    "chase_block_candles": 3,
    "chase_block_pct": 0.02,
    # Volume must still be alive (lower bar than v1's climax spike).
    "volume_window": 48,         # 12h rolling baseline
    "volume_mult": 1.5,
    # Optional pair-level trend confirm.
    "pair_ema_period": 50,
    "require_pair_above_ema": True,
}


def add_indicators(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Add the numeric columns the entry gates read. Backward-looking only."""
    df = df.copy()
    n = params["impulse_lookback"]
    window_high = df["close"].rolling(n).max()
    window_low = df["close"].rolling(n).min()
    # Prior move over the window, and how far the current close has pulled back
    # from the window high. "the high" is the highest *close*, not `high`.
    df["impulse_pct"] = (window_high - window_low) / window_low
    df["drawdown_from_high"] = (window_high - df["close"]) / window_high
    df["vol_avg"] = df["volume"].rolling(params["volume_window"]).mean()
    df["pct_change_3"] = df["close"].pct_change(params["chase_block_candles"])
    df["ema_pair"] = df["close"].ewm(
        span=params["pair_ema_period"], adjust=False
    ).mean()
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
    """Long only in an up regime, on a pullback (not a chase) of a real move
    that still has volume. `regime_ok` is a bool (broadcast) or a Series already
    aligned to `df` (as the strategy passes it after the informative merge)."""
    if isinstance(regime_ok, pd.Series):
        regime = regime_ok.reindex(df.index).fillna(False).astype(bool)
    else:
        regime = pd.Series(bool(regime_ok), index=df.index)

    impulse_ok = df["impulse_pct"] >= params["impulse_min_pct"]
    pullback_ok = (df["drawdown_from_high"] >= params["pullback_min_pct"]) & (
        df["drawdown_from_high"] <= params["pullback_max_pct"]
    )
    volume_ok = df["vol_avg"].notna() & (
        df["volume"] >= params["volume_mult"] * df["vol_avg"]
    )
    # Block if the last 3 bars already ran; NaN (warmup) -> False -> no entry.
    chase_ok = df["pct_change_3"] < params["chase_block_pct"]
    if params["require_pair_above_ema"]:
        pair_ok = df["close"] > df["ema_pair"]
    else:
        pair_ok = pd.Series(True, index=df.index)

    mask = regime & impulse_ok & pullback_ok & volume_ok & chase_ok & pair_ok
    return mask.fillna(False)
