"""Adapter based on the original 54_multi_asset_long_short_hedge.py TqSdk example."""
from .._legacy import LegacyIndicatorStrategy
from .params import FAST_PERIOD, SLOW_PERIOD, SIGNAL_PERIOD, TIMEFRAME, DIRECTION, VOLUME


class Strategy(LegacyIndicatorStrategy):
    ALGORITHM = "ma_cross"
    DEFAULT_FAST = FAST_PERIOD
    DEFAULT_SLOW = SLOW_PERIOD
    DEFAULT_SIGNAL = SIGNAL_PERIOD
    DEFAULT_VOLUME = VOLUME

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        merged = {"fast_period": FAST_PERIOD, "slow_period": SLOW_PERIOD,
                  "signal_period": SIGNAL_PERIOD, "timeframe": TIMEFRAME,
                  "direction": DIRECTION, "volume": VOLUME}
        merged.update(params or {})
        super().__init__(strategy_id, contract_info, data_pool, merged)
