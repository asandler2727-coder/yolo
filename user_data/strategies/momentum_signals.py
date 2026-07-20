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
    "range_lookback": 32,       # ITER 2 SWEEP (frozen default is 48 = 12h)
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
