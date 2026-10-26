"""Rules transcribed from the original 35–45 single-contract examples."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _side(strategy):
    position = strategy.position.net_volume
    return (position > 0) - (position < 0)


def _enter(strategy, side, price):
    strategy._rule_state["entry_price"] = float(price)
    return side


def _pnl(strategy, price):
    entry = strategy._rule_state.get("entry_price", price)
    side = _side(strategy)
    return side * (price - entry) / entry if entry else 0.0


def _simple_rsi(close, period=14):
    changes = np.diff(close.iloc[-period - 1:].to_numpy())
    gain = np.maximum(changes, 0).mean()
    loss = np.maximum(-changes, 0).mean()
    return 100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)


def _wilder_rsi(close, period=14):
    change = close.diff()
    # tqsdk.ta.RSI uses SMA(max(change, 0), n, 1) /
    # SMA(abs(change), n, 1). The first numerator observation is zero.
    positive = pd.Series(np.where(change > 0, change, 0.0), index=close.index)
    numerator = positive.ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    denominator = change.abs().ewm(alpha=1/period, adjust=False).mean().iloc[-1]
    return numerator / denominator * 100 if denominator else float("nan")


def _bands(close, period=20, multiple=2):
    values = close.iloc[-period:].to_numpy()
    middle = values.mean()
    spread = values.std() * multiple
    return middle + spread, middle, middle - spread


def _atr(frame, period=14):
    previous = frame.close.shift()
    tr = pd.concat([frame.high - frame.low,
                    (frame.high - previous).abs(),
                    (frame.low - previous).abs()], axis=1).max(axis=1)
    return tr.iloc[-period:].mean()


def _35(strategy, frame):
    if len(frame) < 30:
        return None
    price = frame.close.iloc[-1]
    rsi = _wilder_rsi(frame.close)
    side = _side(strategy)
    if side == 0:
        high, low = frame.high.iloc[-20:].max(), frame.low.iloc[-20:].min()
        for level in (0.236, 0.382, 0.5, 0.618, 0.786):
            support = high - (high - low) * level
            if support and abs(price - support) / support < .005 and rsi < 35:
                return _enter(strategy, 1, price)
    elif side == 1:
        entry = strategy._rule_state.get("entry_price", price)
        if price < entry - 2.5 * _atr(frame) or rsi > 65:
            return 0
    return None


def _36(strategy, frame):
    if len(frame) < 60:
        return None
    close = frame.close
    short = np.mean([close.iloc[-p:].mean() for p in (3, 5, 8, 10, 12, 15)])
    long = np.mean([close.iloc[-p:].mean() for p in (30, 35, 40, 45, 50, 60)])
    price = close.iloc[-1]
    if _side(strategy) == 0 and short > long:
        return _enter(strategy, 1, price)
    if _side(strategy) == 1 and (short < long or price < strategy._rule_state.get("entry_price", price) * .97):
        return 0
    return None


def _37(strategy, frame):
    if len(frame) < 24:
        return None
    price = frame.close.iloc[-1]
    middle = frame.close.iloc[-20:].mean()
    spread = _atr(frame) * 2.5
    side = _side(strategy)
    if side == 0:
        if price > middle + spread:
            return _enter(strategy, 1, price)
        if price < middle - spread:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) < -.02 or _pnl(strategy, price) > .04 or (side == 1 and price < middle) or (side == -1 and price > middle):
        return 0
    return None


def _38(strategy, frame):
    if len(frame) < 25:
        return None
    price = frame.close.iloc[-1]
    # This source calls TqSdk BOLL, whose rolling standard deviation is the
    # pandas sample standard deviation. _bands is the population-std helper
    # used by the manually coded 42_bollinger_mean_reversion example.
    middle = frame.close.iloc[-20:].mean()
    spread = 2 * frame.close.iloc[-20:].std()
    upper, lower = middle + spread, middle - spread
    side = _side(strategy)
    if side == 0:
        if price <= lower:
            return _enter(strategy, 1, price)
        if price >= upper:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) < -.015 or (side == 1 and price >= middle) or (side == -1 and price <= middle):
        return 0
    return None


def _39(strategy, frame):
    if len(frame) < 30:
        return None
    price = frame.close.iloc[-1]
    side = _side(strategy)
    if side == 0:
        average_volume = frame.volume.iloc[-20:].mean()
        # The source includes the current high/low in these extrema. Preserve
        # its strict inequalities, including their nontriggering behavior.
        if price > frame.high.iloc[-20:].max() and frame.volume.iloc[-1] > average_volume * 1.5:
            return _enter(strategy, 1, price)
        if price < frame.low.iloc[-20:].min() and frame.volume.iloc[-1] > average_volume * 1.5:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) < -.02 or _pnl(strategy, price) > .05:
        return 0
    return None


def _40(strategy, frame):
    if len(frame) < 60:
        return None
    close = frame.close
    price = close.iloc[-1]
    side = _side(strategy)
    momentum = price - close.iloc[-14]
    accelerating = momentum > close.iloc[-14] - close.iloc[-28]
    trend_up = price > close.iloc[-50:].mean()
    if side == 0:
        if trend_up and momentum > 0 and accelerating:
            return _enter(strategy, 1, price)
        if not trend_up and momentum < 0 and not accelerating:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) <= -.02 or _pnl(strategy, price) >= .06:
        return 0
    return None


def _41(strategy, frame):
    if len(frame) < 70:
        return None
    close = frame.close
    price = close.iloc[-1]
    short, middle, long = (close.iloc[-n:].mean() for n in (10, 30, 60))
    side = _side(strategy)
    if side == 0 and short > middle > long and price <= middle * 1.01:
        return _enter(strategy, 1, price)
    if side == 1 and (short < middle < long or _pnl(strategy, price) <= -.025 or _pnl(strategy, price) >= .08):
        return 0
    return None


def _42(strategy, frame):
    if len(frame) < 44:
        return None
    price = frame.close.iloc[-1]
    upper, _, lower = _bands(frame.close)
    rsi = _simple_rsi(frame.close)
    side = _side(strategy)
    if side == 0:
        if price <= lower and rsi < 35:
            return _enter(strategy, 1, price)
        if price >= upper and rsi > 65:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) <= -.015 or _pnl(strategy, price) >= .03:
        return 0
    return None


def _43(strategy, frame):
    if len(frame) < 80:
        return None
    close = frame.close
    price = close.iloc[-1]
    fast, slow = close.iloc[-10:].mean(), close.iloc[-60:].mean()
    state = strategy._rule_state
    if "previous_fast" not in state:
        state["previous_fast"], state["previous_slow"] = fast, slow
        return None
    gold = state["previous_fast"] <= state["previous_slow"] and fast > slow
    death = state["previous_fast"] >= state["previous_slow"] and fast < slow
    state["previous_fast"], state["previous_slow"] = fast, slow
    if _side(strategy) == 0 and frame.volume.iloc[-1] > 1.5 * frame.volume.iloc[-20:].mean():
        if gold:
            return _enter(strategy, 1, price)
        if death:
            return _enter(strategy, -1, price)
    elif _side(strategy) and (_pnl(strategy, price) <= -.02 or _pnl(strategy, price) >= .06):
        return 0
    return None


def _44(strategy, frame):
    if len(frame) < 70:
        return None
    close = frame.close
    price = close.iloc[-1]
    short = np.mean([close.iloc[-n:].mean() for n in (3, 5, 8, 10, 12, 15)])
    long = np.mean([close.iloc[-n:].mean() for n in (30, 35, 40, 45, 50, 60)])
    if _side(strategy) == 0:
        if short > long:
            return _enter(strategy, 1, price)
        if short < long:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) <= -.02 or _pnl(strategy, price) >= .04:
        return 0
    return None


def _45(strategy, frame):
    if len(frame) < 84:
        return None
    close = frame.close
    price = close.iloc[-1]
    average = close.iloc[-60:].mean()
    rsi = _simple_rsi(close)
    if _side(strategy) == 0:
        if price > average and rsi < 30:
            return _enter(strategy, 1, price)
        if price < average and rsi > 70:
            return _enter(strategy, -1, price)
    elif _pnl(strategy, price) <= -.015 or _pnl(strategy, price) >= .03:
        return 0
    return None


RULES = {
    "35_fibonacci_retracement": _35,
    "36_guppy_ma": _36,
    "37_volatility_breakout": _37,
    "38_boll_mean_reversion": _38,
    "39_vwap_breakout_volume": _39,
    "40_momentum_acceleration": _40,
    "41_bullish_ma_arrangement": _41,
    "42_bollinger_mean_reversion": _42,
    "43_ma_crossover": _43,
    "44_guppy_ma_trend": _44,
    "45_trend_filtered_rsi": _45,
}
