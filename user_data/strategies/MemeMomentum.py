from datetime import datetime, timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy

from momentum_signals import DEFAULT_PARAMS, add_indicators, entry_mask


class MemeMomentum(IStrategy):
    """Spec 2026-07-18 §5: long-only 15m momentum. Entries = pump + volume spike.
    Exits = ROI ladder, hard stop, trailing stop, stagnation timeout.
    Protections here implement spec §6 and are never weakened (spec §8.5)."""

    INTERFACE_VERSION = 3
    timeframe = "15m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count = 60  # > volume_window(48) + momentum_candles(8)

    params = DEFAULT_PARAMS

    # Exit ladder (minutes: profit). Tuned in Task 6; these are starting values.
    minimal_roi = {"0": 0.10, "120": 0.04, "360": 0.02}
    stoploss = -0.06
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

    stagnation_hours = 12  # close flat trades after this long

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return add_indicators(dataframe, self.params)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[entry_mask(dataframe, self.params), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe  # exits handled by ROI/stoploss/trailing/custom_exit

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        if (current_time - trade.open_date_utc) > timedelta(hours=self.stagnation_hours) \
                and current_profit < 0.01:
            return "stagnation_timeout"
        return None
