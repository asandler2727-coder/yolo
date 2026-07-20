from datetime import datetime, timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair

from momentum_signals import (
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    limit_entry_price,
    regime_mask_from_btc,
    resample_1h,
)


class MemeMomentum(IStrategy):
    """v2 (redesign 2026-07-19): long-only 15m pullback-in-uptrend.

    Entry = up regime (BTC 1h trend) + prior impulse + pullback into a support
    band + volume alive + anti-chase, from the pure-pandas momentum_signals
    module. b' (spec 2026-07-20-yolo-b-prime-limit-entry.md): the entry rests
    as a limit 2% below the signal-time price with a 4h unfilled timeout
    (config), buying the measured post-signal shakeout. Exits are fee-aware
    (~0.8% round-trip taker): a 3%/2%/1% ROI ladder, a -4% hard stop, a tight
    trailing lock, and a 6h stagnation timeout.
    Protections implement spec §6 and are never weakened (spec §8.5).

    Regime source: BTC/USD is the Kraken pair actually in the dataset. Only 15m
    BTC data exists, so the 1h regime is resampled from it and merged back with
    merge_informative_pair (which adds the offset that prevents look-ahead). If
    BTC data is missing for a window, regime fails closed -> no entries.
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

    # Fee-aware exits (redesign §2). Minutes -> target profit.
    minimal_roi = {"0": 0.03, "60": 0.02, "180": 0.01}
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.012
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    stagnation_hours = 6  # close flat trades after this long

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
        return dataframe  # exits handled by ROI/stoploss/trailing/custom_exit

    def custom_entry_price(self, pair: str, trade, current_time: datetime,
                           proposed_rate: float, entry_tag, **kwargs) -> float:
        # b': rest the entry below the shakeout; unfilledtimeout cancels stale
        # orders. Needs custom_price_max_distance_ratio > depth in the config,
        # or freqtrade silently clamps the price (default ratio == our depth).
        return limit_entry_price(proposed_rate, self.params["entry_limit_depth"])

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        if (current_time - trade.open_date_utc) > timedelta(hours=self.stagnation_hours) \
                and current_profit < 0.01:
            return "stagnation_timeout"
        return None
