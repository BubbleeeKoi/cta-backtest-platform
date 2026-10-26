"""Stateful rules copied from the original trend strategy decisions."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._source_rules_late import _side
from ._source_rules_standard import _true_range


def _09(strategy, frame):
    if len(frame) < 31:
        return None
    close = frame.close
    fast, slow = close.rolling(10).mean(), close.rolling(30).mean()
    atr = _true_range(frame).ewm(span=14, adjust=False).mean().iloc[-1]
    price = close.iloc[-1]
    state = strategy._rule_state
    side = _side(strategy)
    distance = 2 * atr
    if side == 1:
        state["long_stop"] = max(state.get("long_stop", 0), price-distance)
        if price < state["long_stop"]:
            state["long_stop"] = 0
            return 0
    elif side == -1:
        state["short_stop"] = min(state.get("short_stop", float("inf")), price+distance)
        if price > state["short_stop"]:
            state["short_stop"] = float("inf")
            return 0
    if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1]:
        state["long_stop"] = price-distance
        state["short_stop"] = float("inf")
        return 1
    if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]:
        state["short_stop"] = price+distance
        state["long_stop"] = 0
        return -1
    return None


def _18_psar(strategy, frame):
    if len(frame) < 3:
        return None
    high, low, close = (frame[column].to_numpy() for column in ("high", "low", "close"))
    trend = 1 if close[1] > close[0] else -1
    sar = low[0] if trend == 1 else high[0]
    extreme = high[0] if trend == 1 else low[0]
    acceleration = .02
    previous_trend = trend
    for i in range(1, len(close)):
        previous_trend = trend
        value = sar + acceleration * (extreme-sar)
        if trend == 1:
            value = min(value, low[i-1], low[i-2] if i >= 2 else low[i-1])
            if low[i] < value:
                trend, sar, extreme, acceleration = -1, extreme, low[i], .02
            else:
                sar = value
                if high[i] > extreme:
                    extreme, acceleration = high[i], min(acceleration+.02, .2)
        else:
            value = max(value, high[i-1], high[i-2] if i >= 2 else high[i-1])
            if high[i] > value:
                trend, sar, extreme, acceleration = 1, extreme, high[i], .02
            else:
                sar = value
                if low[i] < extreme:
                    extreme, acceleration = low[i], min(acceleration+.02, .2)
    return trend if trend != previous_trend else None


def _dmi(frame, period=14):
    high, low, close = (frame[column].to_numpy(dtype=float) for column in ("high", "low", "close"))
    n = len(close)
    plus_dm, minus_dm, tr = np.zeros(n), np.zeros(n), np.zeros(n)
    for i in range(1, n):
        up, down = high[i]-high[i-1], low[i-1]-low[i]
        tr[i] = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down
    tr_sum, plus_sum, minus_sum = (np.zeros(n) for _ in range(3))
    if n <= period:
        return np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
    tr_sum[period] = tr[1:period+1].sum()
    plus_sum[period] = plus_dm[1:period+1].sum()
    minus_sum[period] = minus_dm[1:period+1].sum()
    for i in range(period+1, n):
        tr_sum[i] = tr_sum[i-1]*(period-1)/period + tr[i]
        plus_sum[i] = plus_sum[i-1]*(period-1)/period + plus_dm[i]
        minus_sum[i] = minus_sum[i-1]*(period-1)/period + minus_dm[i]
    pdi = np.divide(plus_sum*100, tr_sum, out=np.zeros(n), where=tr_sum>0)
    mdi = np.divide(minus_sum*100, tr_sum, out=np.zeros(n), where=tr_sum>0)
    dx = np.divide(abs(pdi-mdi)*100, pdi+mdi, out=np.zeros(n), where=(pdi+mdi)>0)
    adx = np.zeros(n)
    if n > period*2:
        adx[period*2] = dx[period:period*2].mean()
        for i in range(period*2+1, n):
            adx[i] = (adx[i-1]*(period-1)+dx[i])/period
    atr = np.zeros(n)
    atr[period] = tr[1:period+1].mean()
    for i in range(period+1, n):
        atr[i] = (atr[i-1]*(period-1)+tr[i])/period
    return pdi, mdi, adx, atr


def _29(strategy, frame):
    if len(frame) < 47:
        return None
    pdi, mdi, adx, atr = _dmi(frame)
    price = frame.close.iloc[-1]
    side = _side(strategy)
    state = strategy._rule_state
    if side:
        stop = state.get("stop")
        candidate = price-2*atr[-1] if side > 0 else price+2*atr[-1]
        stop = candidate if stop is None else max(stop, candidate) if side > 0 else min(stop, candidate)
        state["stop"] = stop
        if (side > 0 and (price < stop or adx[-1] < 20 or pdi[-1] < mdi[-1] and pdi[-2] >= mdi[-2])
                or side < 0 and (price > stop or adx[-1] < 20 or pdi[-1] > mdi[-1] and pdi[-2] <= mdi[-2])):
            state["stop"] = None
            return 0
        return None
    if adx[-1] >= 25 and pdi[-1] > mdi[-1] and price > frame.high.iloc[-11:-1].max():
        state["stop"] = price-2*atr[-1]
        return 1
    if adx[-1] >= 25 and mdi[-1] > pdi[-1] and price < frame.low.iloc[-11:-1].min():
        state["stop"] = price+2*atr[-1]
        return -1
    return None


def _30(strategy, frame):
    if len(frame) < 15:
        return None
    atr = _true_range(frame).ewm(alpha=1/10, adjust=False).mean()
    high, low, close = (frame[column].to_numpy() for column in ("high", "low", "close"))
    basic_upper = (high+low)/2 + 3*atr.to_numpy()
    basic_lower = (high+low)/2 - 3*atr.to_numpy()
    upper, lower, direction = basic_upper[0], basic_lower[0], -1
    prior_direction = direction
    for i in range(1, len(frame)):
        upper = basic_upper[i] if basic_upper[i] < upper or close[i-1] > upper else upper
        lower = basic_lower[i] if basic_lower[i] > lower or close[i-1] < lower else lower
        prior_direction = direction
        if direction < 0 and close[i] > upper:
            direction = 1
        elif direction > 0 and close[i] < lower:
            direction = -1
    return direction if direction != prior_direction else None


def _32_cloud(strategy, frame):
    # The original stores close[-27] as both chikou_span and past_price_26.
    # Its strict comparison of these identical values never passes, so it
    # cannot enter a position. Keep that actual source behavior.
    return None


def _57_volatility_distribution(close, days, bars_per_day):
    period = days * bars_per_day
    if len(close) < period+1:
        return np.array([])
    # Each source window computes pct_change then std, excluding the first
    # return within that window. This rolling sample has the same members.
    returns = close.pct_change()
    values = returns.rolling(period-1).std().iloc[period-1:].to_numpy() * np.sqrt(252)
    return values[np.isfinite(values) & (values > 0)]


def _57(strategy, frame):
    bars_per_day = 24 if strategy.timeframe == "1h" else 1 if strategy.timeframe == "1d" else 96
    if len(frame) < 60*bars_per_day + 40:
        return None
    close = frame.close
    price = close.iloc[-1]
    atr = _true_range(frame).iloc[-14:].mean()
    returns = close.pct_change().dropna()
    total_std = returns.std()
    if not np.isfinite(atr) or not np.isfinite(total_std) or total_std == 0:
        return None
    up = returns.clip(lower=0).std()
    down = (-returns.clip(upper=0)).std()
    adx = min(abs(up-down)/(up+down)*100, 100) if up+down else 0
    middle = close.iloc[-20:].mean()
    deviation = close.iloc[-20:].std()
    upper, lower = middle+2*deviation, middle-2*deviation
    current_vol = atr / price if price > 0 else 0
    annual_vol = current_vol*np.sqrt(252)
    percentile = .5
    valid = 0
    for weight, days in ((.2, 5), (.3, 20), (.5, 60)):
        distribution = _57_volatility_distribution(close, days, bars_per_day)
        if len(distribution) < 5:
            continue
        top, bottom = np.percentile(distribution, (75, 25))
        if top > bottom:
            percentile += weight * max(0, min(1, (annual_vol-bottom)/(top-bottom)))
            valid += 1
    if valid == 0:
        percentile = .5
    state = strategy._rule_state
    side = _side(strategy)
    if side == 0:
        if price > upper and adx > 25 and percentile <= .9:
            state.update(entry_price=price, peak_price=price)
            return 1
        if price < lower and adx > 25 and percentile > .5:
            state.update(entry_price=price, peak_price=price)
            return -1
        return None
    entry = state.get("entry_price", price)
    peak = state.get("peak_price", price)
    peak = max(peak, price) if side > 0 else min(peak, price)
    state["peak_price"] = peak
    multiple = 3 if percentile > .75 else 2 if percentile > .25 else 1.5
    stop = peak - side * multiple * atr
    if side > 0 and price < stop or side < 0 and price > stop:
        state.clear()
        return 0
    if side > 0 and peak > entry*1.02 and price < entry*1.01:
        state.clear()
        return 0
    if side < 0 and peak < entry*.98 and price > entry*.99:
        state.clear()
        return 0
    return None


RULES = {
    "09_atr_stop_loss": _09,
    "18_parabolic_sar": _18_psar,
    "29_adx_trend_filter": _29,
    "30_supertrend": _30,
    "32_ichimoku_cloud": _32_cloud,
    "57_adaptive_volatility_breakout": _57,
}
