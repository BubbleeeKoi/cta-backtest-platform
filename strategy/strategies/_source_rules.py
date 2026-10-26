"""Completed-bar implementations of the original single-symbol entry/exit rules.

The selectable 1h/1d period determines the observations.  A rule returns
None to retain the current target, zero to flatten, or +/-1 to target a side.
"""
from __future__ import annotations

import math
from collections import deque
import pandas as pd

from ._source_factor import FactorStrategy


# TqSdk's get_kline_serial keeps a fixed number of observations. Recursive
# indicators (SAR, KDJ, EMA, ADX) can change if this window is different.
_SOURCE_LENGTHS = {
    "01_double_ma": 30, "02_boll_breakout": 30,
    "03_rsi_mean_reversion": 42, "05_turtle_trading": 25,
    "07_kdj_signal": 299, "08_cci_breakout": 200,
    "09_atr_stop_loss": 299, "10_momentum_breakout": 300,
    "11_mean_reversion_zscore": 300, "14_volume_price_trend": 150,
    "15_donchian_channel": 25, "16_aroon_trend": 200,
    "17_stochastic_rsi": 299, "18_bollinger_mean_reversion": 200,
    "18_parabolic_sar": 299, "18_vwap_mean_reversion": 200,
    "19_atr_channel_breakout": 200, "19_ichimoku_cloud": 200,
    "19_williams_r": 300, "20_hull_ma": 300,
    "21_keltner_channel": 299, "22_trix_trend": 499,
    "23_pivot_point": 500, "24_r_breaker": 300,
    "26_chaikin_money_flow": 30, "28_obv_trend": 500,
    "28_volatility_breakout": 58, "29_adx_trend_filter": 599,
    "30_supertrend": 59, "31_vwap_mean_reversion": 500,
    "32_ichimoku_cloud": 200, "32_linear_regression_channel": 200,
    "33_boll_mean_reversion": 30, "34_vwap_breakout": 200,
    "35_fibonacci_retracement": 200, "36_guppy_ma": 100,
    "37_volatility_breakout": 50, "38_boll_mean_reversion": 40,
    "39_vwap_breakout_volume": 50, "40_momentum_acceleration": 100,
    "41_bullish_ma_arrangement": 100, "42_bollinger_mean_reversion": 100,
    "43_ma_crossover": 150, "44_guppy_ma_trend": 100,
    "45_trend_filtered_rsi": 100,
}


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame.close.shift(1)
    true_range = pd.concat(
        [frame.high - frame.low, (frame.high - previous).abs(),
         (frame.low - previous).abs()], axis=1,
    ).max(axis=1)
    return true_range.rolling(period).mean()


def _cross_up(a: pd.Series, b: pd.Series | float) -> bool:
    return len(a) > 1 and a.iloc[-2] <= (b.iloc[-2] if isinstance(b, pd.Series) else b) and a.iloc[-1] > (b.iloc[-1] if isinstance(b, pd.Series) else b)


def _cross_down(a: pd.Series, b: pd.Series | float) -> bool:
    return len(a) > 1 and a.iloc[-2] >= (b.iloc[-2] if isinstance(b, pd.Series) else b) and a.iloc[-1] < (b.iloc[-1] if isinstance(b, pd.Series) else b)


def _rsi_wilder(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    return 100 - 100 / (1 + rs)


class SourceRuleStrategy(FactorStrategy):
    """Shared bar transport, with a separate rule for each original strategy."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self._rule_state: dict[str, float | int | bool] = {}
        self._completed_count = 0
        package = type(self).__module__.split(".")[-2]
        if package == "57_adaptive_volatility_breakout":
            bars_per_day = 24 if self.timeframe == "1h" else 1 if self.timeframe == "1d" else 96
            self._source_bars = deque(maxlen=60 * bars_per_day + 40)
        else:
            self._source_bars = deque(maxlen=_SOURCE_LENGTHS[package])

    def _indicator_signal(self) -> int | None:
        if self._bucket is None:
            return None
        completed = dict(self._bucket)
        completed["timestamp"] = self._bucket_start
        self._source_bars.append(completed)
        self._completed_count += 1
        frame = pd.DataFrame(self._source_bars)
        package = type(self).__module__.split(".")[-2]
        rule = _RULES.get(package)
        if rule is None:
            raise NotImplementedError(f"No source rule for {package}")
        return rule(self, frame)


def _double_ma(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 21:
        return None
    short = frame.close.rolling(5).mean()
    long = frame.close.rolling(20).mean()
    if _cross_up(short, long):
        return 1
    if _cross_down(short, long):
        return -1
    return None


def _boll_breakout(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 20:
        return None
    close = frame.close
    middle = close.tail(20).mean()
    std = close.tail(20).std()
    if not math.isfinite(std) or middle <= 0:
        return None
    upper, lower = middle + 2 * std, middle - 2 * std
    if (upper - lower) / middle < 0.01:
        return None
    price = close.iloc[-1]
    if price > upper:
        return 1
    if price < lower:
        return -1
    if price < middle or price > middle:
        return 0
    return None


def _rsi_reversion(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 15:
        return None
    rsi = _rsi_wilder(frame.close, 14).iloc[-1]
    if not math.isfinite(rsi):
        return None
    if rsi < 30:
        return 1
    if rsi > 70:
        return -1
    if 40 < rsi < 60:
        return 0
    return None


def _turtle(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 21:
        return None
    price = frame.close.iloc[-1]
    # The original compares the completed close with a channel that already
    # contains the same completed bar. Its strict breaks cannot fire.
    high_entry = frame.high.iloc[-20:].max()
    low_entry = frame.low.iloc[-20:].min()
    high_exit = frame.high.iloc[-10:].max()
    low_exit = frame.low.iloc[-10:].min()
    if price > high_entry:
        return 1
    if price < low_entry:
        return -1
    if strategy.position.net_volume > 0 and price < low_exit:
        return 0
    if strategy.position.net_volume < 0 and price > high_exit:
        return 0
    return None


def _kdj(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 10:
        return None
    highest = frame.high.rolling(9).max()
    lowest = frame.low.rolling(9).min()
    denominator = (highest - lowest).replace(0, 1)
    rsv = (frame.close - lowest) / denominator * 100
    k_values, d_values = [], []
    k_prev = d_prev = 50.0
    for value in rsv:
        if pd.isna(value):
            k_values.append(float("nan"))
            d_values.append(float("nan"))
            continue
        k_prev = k_prev * (2 / 3) + float(value) / 3
        d_prev = d_prev * (2 / 3) + k_prev / 3
        k_values.append(k_prev)
        d_values.append(d_prev)
    k, d = k_values[-1], d_values[-1]
    previous_k, previous_d = k_values[-2], d_values[-2]
    if strategy.position.net_volume > 0 and k > 80:
        return 0
    if strategy.position.net_volume < 0 and k < 20:
        return 0
    if previous_k < previous_d and k > d and k < 50:
        return 1
    if previous_k > previous_d and k < d and k > 50:
        return -1
    return None


def _cci_breakout(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 15:
        return None
    typical = (frame.high + frame.low + frame.close) / 3
    mean = typical.rolling(14).mean()
    deviation = typical.rolling(14).apply(
        lambda x: abs(x - x.mean()).mean(), raw=True,
    )
    cci = ((typical - mean) / (0.015 * deviation.replace(0, float("nan")))).fillna(0)
    if _cross_down(cci, 100) and strategy.position.net_volume > 0:
        return 0
    if _cross_up(cci, -100) and strategy.position.net_volume < 0:
        return 0
    if _cross_up(cci, 200):
        return 1
    if _cross_down(cci, -200):
        return -1
    return None


def _momentum_breakout(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 60:
        return None
    close = frame.close
    earlier = close.iloc[-21]
    if earlier == 0:
        return None
    momentum = (close.iloc[-1] - earlier) / earlier * 100
    if strategy.position.net_volume > 0 and momentum < 0.5:
        return 0
    if strategy.position.net_volume < 0 and momentum > -0.5:
        return 0
    ma60 = close.tail(60).mean()
    if momentum > 2 and close.iloc[-1] > ma60:
        return 1
    if momentum < -2 and close.iloc[-1] < ma60:
        return -1
    return None


def _zscore_reversion(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 20:
        return None
    close = frame.close
    sample = close.tail(20)
    std = sample.std()
    if not math.isfinite(std) or std == 0:
        return None
    z = (close.iloc[-1] - sample.mean()) / std
    state = strategy._rule_state
    current = strategy.position.net_volume
    if current:
        bars_held = strategy._completed_count - int(state.get("entry_bar", strategy._completed_count))
        if (current > 0 and z > -0.5 or current < 0 and z < 0.5
                or bars_held >= 10):
            return 0
    if current == 0 and z < -2:
        state["entry_bar"] = strategy._completed_count
        return 1
    if current == 0 and z > 2:
        state["entry_bar"] = strategy._completed_count
        return -1
    return None


def _volume_price(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 21:
        return None
    price = frame.close.iloc[-1]
    if strategy.position.net_volume > 0 and price < frame.low.tail(10).min():
        return 0
    if strategy.position.net_volume < 0 and price > frame.high.tail(10).max():
        return 0
    volume_average = frame.volume.tail(20).mean()
    if volume_average <= 0 or frame.volume.iloc[-1] < 1.5 * volume_average:
        return None
    if price > frame.close.iloc[-21:-1].max():
        return 1
    if price < frame.close.iloc[-21:-1].min():
        return -1
    return None


def _donchian(strategy: SourceRuleStrategy, frame: pd.DataFrame) -> int | None:
    if len(frame) < 21:
        return None
    price = frame.close.iloc[-1]
    if price > frame.high.iloc[-20:].max():
        return 1
    if price < frame.low.iloc[-20:].min():
        return -1
    if price < frame.low.iloc[-10:].min():
        return 0
    if price > frame.high.iloc[-10:].max():
        return 0
    return None


_RULES = {
    "01_double_ma": _double_ma,
    "02_boll_breakout": _boll_breakout,
    "03_rsi_mean_reversion": _rsi_reversion,
    "05_turtle_trading": _turtle,
    "07_kdj_signal": _kdj,
    "08_cci_breakout": _cci_breakout,
    "10_momentum_breakout": _momentum_breakout,
    "11_mean_reversion_zscore": _zscore_reversion,
    "14_volume_price_trend": _volume_price,
    "15_donchian_channel": _donchian,
}

from ._source_rules_late import RULES as _LATE_RULES
from ._source_rules_mid import RULES as _MID_RULES
from ._source_rules_standard import RULES as _STANDARD_RULES
from ._source_rules_complex import RULES as _COMPLEX_RULES
from ._source_rules_levels import RULES as _LEVEL_RULES
_RULES.update(_LATE_RULES)
_RULES.update(_MID_RULES)
_RULES.update(_STANDARD_RULES)
_RULES.update(_COMPLEX_RULES)
_RULES.update(_LEVEL_RULES)
