import logging
from datetime import timedelta

from pandas import DataFrame

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, merge_informative_pair

from momentum_signals import (
    DEFAULT_PARAMS,
    add_indicators,
    entry_mask,
    fill_allowed,
    regime_mask_from_btc,
    resample_1h,
    signal_bar_cap,
)

logger = logging.getLogger(__name__)


class MemeMomentum(IStrategy):
    """Family A (2026-07-20): long-only 15m range-coil breakout in a BTC
    up-regime. Spec: docs/superpowers/specs/2026-07-20-yolo-family-a-range-breakout.md.

    Entry = up regime (BTC 1h trend, fail-closed) + tight 12h range + close
    above the range high on 2x volume, never more than 1.5% above the range
    high — enforced twice: at the signal (entry_mask) and AT THE FILL
    (confirm_trade_entry vetoes any fill above the signal bar's frozen
    entry_cap; a candle can close inside the cap and gap open above it, and
    buying that gap would be v1 in disguise). Entries are market orders.

    Exits: -4% stop, late-peak ROI ladder 5/3/1.5%, tight trailing lock after
    +3%. NO stagnation exit by default (Austin's gate amendment — timed cuts
    are dev knobs; hold/slot diagnostics are mandatory instead).

    Sizing (Austin's gate amendment): 10% of current total equity per trade,
    max 10 open; below a pair's minimum -> skip and log.

    Regime source: only 15m BTC/USD data exists, so the 1h regime is
    resampled from it and merged back with merge_informative_pair (which adds
    the +45m offset that prevents look-ahead). Missing BTC data -> regime
    fails closed -> no entries. Protections implement master spec s6 and are
    never weakened (s8.5).
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

    # Sizing: fraction of current total equity per trade.
    stake_fraction = 0.10

    # Exits (spec s3): winners in this market peak late.
    minimal_roi = {"0": 0.05, "240": 0.03, "480": 0.015}
    stoploss = -0.04
    trailing_stop = True
    trailing_stop_positive = 0.012
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    # Stagnation exit OFF by default (Austin's gate amendment). Dev knob
    # values: 4, 8, 12 (hours). None = no timed exit.
    stagnation_hours = None

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
        return dataframe  # exits handled by ROI/stoploss/trailing (+ dev knob)

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float,
                            rate: float, time_in_force: str, current_time,
                            entry_tag, side: str, **kwargs) -> bool:
        """Anti-chase cap enforced AT THE FILL (spec s3): veto any fill above
        the SIGNAL bar's frozen entry_cap. Fails closed when the signal bar
        cannot be found. Every veto is logged for the dev diagnostics."""
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        cap = None
        if df is not None and len(df):
            cap = signal_bar_cap(df, current_time)
        if not fill_allowed(rate, cap):
            logger.info(
                "ENTRY-VETO pair=%s fill=%.10g cap=%s time=%s",
                pair, rate, "none" if cap is None else f"{cap:.10g}", current_time,
            )
            return False
        return True

    def custom_stake_amount(self, pair: str, current_time, current_rate: float,
                            proposed_stake: float, min_stake, max_stake: float,
                            leverage: float, entry_tag, side: str,
                            **kwargs) -> float:
        """10% of current total equity per trade (spec s3 sizing amendment).
        Below the pair minimum -> skip the entry (return 0) and log it, so
        freqtrade never silently bumps a small stake up to the minimum."""
        stake = self.wallets.get_total_stake_amount() * self.stake_fraction
        if min_stake is not None and stake < min_stake:
            logger.info("STAKE-SKIP pair=%s stake=%.2f min=%.2f time=%s",
                        pair, stake, min_stake, current_time)
            return 0
        return min(stake, max_stake)

    def custom_exit(self, pair: str, trade: Trade, current_time,
                    current_rate: float, current_profit: float, **kwargs):
        if self.stagnation_hours is None:  # default: off (gate amendment)
            return None
        if (current_time - trade.open_date_utc) > timedelta(hours=self.stagnation_hours) \
                and current_profit < 0.01:
            return "stagnation_timeout"
        return None
