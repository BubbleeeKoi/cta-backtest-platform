"""Prior-day level rules from the pivot and R-Breaker examples."""
from __future__ import annotations

import pandas as pd


def _prior_day(frame):
    if len(frame) < 2:
        return None
    dates = frame.tradingday.apply(lambda value: pd.Timestamp(value).date())
    current_date = dates.iloc[-1]
    older = frame[dates < current_date]
    if older.empty:
        return None
    prior_date = pd.Timestamp(older.tradingday.iloc[-1]).date()
    sample = older[older.tradingday.apply(lambda value: pd.Timestamp(value).date() == prior_date)]
    return sample.high.max(), sample.low.min(), sample.close.iloc[-1]


def _23(strategy, frame):
    previous = _prior_day(frame)
    if previous is None or len(frame) < 2:
        return None
    high, low, close = previous
    pivot = (high+low+close)/3
    r1, s1 = 2*pivot-low, 2*pivot-high
    now, before = frame.close.iloc[-1], frame.close.iloc[-2]
    if before < pivot <= now:
        return 1
    if before > pivot >= now:
        return -1
    touch = 5  # original TOUCH_RANGE, in price points
    if abs(now-s1) <= touch and now < pivot:
        return 1
    if abs(now-r1) <= touch and now > pivot:
        return -1
    if now >= r1 or now <= s1:
        return 0
    return None


def _24(strategy, frame):
    previous = _prior_day(frame)
    if previous is None or len(frame) < 2:
        return None
    row = frame.iloc[-1]
    timestamp = pd.Timestamp(row.timestamp)
    state = strategy._rule_state
    day = timestamp.date()
    if state.get("day") != day:
        state.update(day=day, touched_sell=False, touched_buy=False)
    if timestamp.hour > 14 or timestamp.hour == 14 and timestamp.minute >= 55:
        return 0
    high, low, close = previous
    pivot = (high+low+close)/3
    levels = {
        "bbreak": high+2*(pivot-low),
        "ssetup": pivot+high-low,
        "senter": 2*pivot-low,
        "benter": 2*pivot-high,
        "bsetup": pivot-high+low,
        "sbreak": low-2*(high-pivot),
    }
    state["touched_sell"] |= row.high >= levels["ssetup"]
    state["touched_buy"] |= row.low <= levels["bsetup"]
    now, before = row.close, frame.close.iloc[-2]
    if now > levels["bbreak"] and before <= levels["bbreak"]:
        return 1
    if now < levels["sbreak"] and before >= levels["sbreak"]:
        return -1
    if state["touched_sell"] and now < levels["senter"] and before >= levels["senter"]:
        state["touched_sell"] = False
        return -1
    if state["touched_buy"] and now > levels["benter"] and before <= levels["benter"]:
        state["touched_buy"] = False
        return 1
    return None


RULES = {"23_pivot_point": _23, "24_r_breaker": _24}
