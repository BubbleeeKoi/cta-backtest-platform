"""Individual signal decisions for the remaining indicator examples."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._source_rules_late import _atr, _bands, _enter, _pnl, _side


def _true_range(frame):
    previous = frame.close.shift(1)
    return pd.concat((frame.high-frame.low, (frame.high-previous).abs(),
                      (frame.low-previous).abs()), axis=1).max(axis=1)


def _19_atr(strategy, frame):
    if len(frame) < 20:
        return None
    middle = frame.close.rolling(20).mean().iloc[-1]
    atr = _true_range(frame).ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    price = frame.close.iloc[-1]
    if price > middle + 2.5 * atr:
        return 1
    if price < middle - 2.5 * atr:
        return -1
    if (price < middle and _side(strategy) > 0) or (price > middle and _side(strategy) < 0):
        return 0
    return None


def _26(strategy, frame):
    if len(frame) < 21:
        return None
    span = (frame.high-frame.low).replace(0, np.nan)
    money = (2*frame.close-frame.high-frame.low) / span * frame.volume
    cmf = money.rolling(20).sum() / frame.volume.rolling(20).sum()
    previous, current = cmf.iloc[-2], cmf.iloc[-1]
    if previous <= .05 < current:
        return 1
    if previous >= -.05 > current:
        return -1
    if previous >= 0 > current or previous <= 0 < current:
        return 0
    return None


def _28_vol(strategy, frame):
    if len(frame) < 30:
        return None
    price = frame.close.iloc[-1]
    # Original extrema include the current close; both strict comparisons
    # below are impossible. Do not silently replace them with prior extrema.
    if price > frame.close.iloc[-20:].max():
        return 1
    if price < frame.close.iloc[-20:].min():
        return -1
    return None


def _28_obv(strategy, frame):
    if len(frame) < 35:
        return None
    close = frame.close
    obv = (np.sign(close.diff()).fillna(0) * frame.volume).cumsum()
    short, long = obv.rolling(10).mean(), obv.rolling(30).mean()
    price_ma = close.rolling(20).mean().iloc[-1]
    state = strategy._rule_state
    if _side(strategy):
        state["hold_bars"] = state.get("hold_bars", 0) + 1
        if state["hold_bars"] >= 20:
            state["hold_bars"] = 0
            return 0
    else:
        state["hold_bars"] = 0
    if short.iloc[-2] <= long.iloc[-2] and short.iloc[-1] > long.iloc[-1] and close.iloc[-1] > price_ma:
        state["hold_bars"] = 0
        return 1
    if short.iloc[-2] >= long.iloc[-2] and short.iloc[-1] < long.iloc[-1] and close.iloc[-1] < price_ma:
        state["hold_bars"] = 0
        return -1
    return None


def _31(strategy, frame):
    # The source VWAP restarts every trading date and uses typical prices.
    if len(frame) < 2:
        return None
    current = frame.iloc[-1]
    day = pd.Timestamp(current.timestamp).date()
    # The original resets cumulative VWAP at the start of each trading day.
    # With one 1d observation there is no within-day variance or z-score.
    sample = frame[frame.timestamp.apply(lambda t: pd.Timestamp(t).date() == day)]
    vol = sample.volume.clip(lower=0)
    total = vol.sum()
    if total < 10:
        return None
    typical = (sample.high + sample.low + sample.close) / 3
    vwap = (typical * vol).sum() / total
    variance = max((typical * typical * vol).sum() / total - vwap*vwap, 0)
    if variance <= 1e-10:
        return None
    z = (current.close - vwap) / np.sqrt(variance)
    side = _side(strategy)
    time = pd.Timestamp(current.timestamp).time()
    if time.hour > 14 or time.hour == 14 and time.minute >= 50:
        return 0
    if side == 1 and (z < -3.5 or abs(z) <= .3):
        return 0
    if side == -1 and (z > 3.5 or abs(z) <= .3):
        return 0
    if side == 0:
        if z >= 2:
            return -1
        if z <= -2:
            return 1
    return None


def _32_linear(strategy, frame):
    if len(frame) < 35:
        return None
    prices = frame.close.iloc[-30:].to_numpy()
    x = np.arange(30, dtype=float)
    slope, intercept = np.polyfit(x, prices, 1)
    errors = prices - (intercept + slope*x)
    se = np.sqrt((errors*errors).sum() / 28)
    if se < 1e-6:
        return None
    middle = intercept + slope*29
    price = frame.close.iloc[-1]
    above, below = price > middle + 2*se, price < middle - 2*se
    state = strategy._rule_state
    prior_above = state.get("above", False)
    prior_below = state.get("below", False)
    state["above"], state["below"] = above, below
    side = _side(strategy)
    if side == 1 and (price < middle-se or abs(price-middle) <= .3*se):
        return 0
    if side == -1 and (price > middle+se or abs(price-middle) <= .3*se):
        return 0
    if side == 0:
        if above and not prior_above and slope > 0:
            return 1
        if below and not prior_below and slope < 0:
            return -1
    return None


def _33(strategy, frame):
    if len(frame) < 25:
        return None
    row = frame.iloc[-1]
    time = pd.Timestamp(row.timestamp)
    if time.hour > 14 or time.hour == 14 and time.minute >= 50:
        return 0
    close = frame.close
    middle = close.iloc[-20:].mean()
    deviation = close.iloc[-20:].std()
    price = close.iloc[-1]
    side = _side(strategy)
    if side == 0:
        if price <= middle-2*deviation:
            return 1
        if price >= middle+2*deviation:
            return -1
    if side == 1 and price >= middle or side == -1 and price <= middle:
        return 0
    return None


def _34(strategy, frame):
    if len(frame) < 21:
        return None
    sample = frame.iloc[-20:]
    volume = sample.volume.sum()
    if volume <= 0:
        return None
    vwap = (sample.close * sample.volume).sum() / volume
    price = frame.close.iloc[-1]
    atr = _atr(frame)
    state = strategy._rule_state
    side = _side(strategy)
    if side == 0:
        recent = frame.volume.iloc[-5:].mean()
        previous = frame.volume.iloc[-10:-5].mean()
        if recent > previous * 1.5:
            if frame.close.iloc[-2] < vwap and price > vwap:
                return _enter(strategy, 1, price)
            if frame.close.iloc[-2] > vwap and price < vwap:
                return _enter(strategy, -1, price)
    else:
        entry = state.get("entry_price", price)
        if (side == 1 and (price < entry-2*atr or price > entry+50 or price < vwap)
                or side == -1 and (price > entry+2*atr or price < entry-50 or price > vwap)):
            return 0
    return None


RULES = {
    "19_atr_channel_breakout": _19_atr,
    "26_chaikin_money_flow": _26,
    "28_volatility_breakout": _28_vol,
    "28_obv_trend": _28_obv,
    "31_vwap_mean_reversion": _31,
    "32_linear_regression_channel": _32_linear,
    "33_boll_mean_reversion": _33,
    "34_vwap_breakout": _34,
}
