"""Original intraday and grid state machines for single-contract backtests."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
import pandas as pd

from framework import OFFSET_CLOSE, OFFSET_OPEN
from ._legacy import LegacyIndicatorStrategy


class DualThrustStrategy(LegacyIndicatorStrategy):
    """Daily range from four completed dates; minute close is the quote proxy."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self._history = deque(maxlen=5)
        self._day = None
        self._daily = None
        self._buy_line = self._sell_line = None

    def on_bar(self, bar, snapshot):
        del snapshot
        timestamp = pd.Timestamp(bar.timestamp)
        day = timestamp.date()
        if day != self._day:
            if self._daily is not None:
                self._history.append(self._daily)
            self._day = day
            self._daily = {"high": bar.high, "low": bar.low,
                           "close": bar.close}
            self._buy_line = self._sell_line = None
            if len(self._history) >= 4:
                previous = list(self._history)[-4:]
                maximum_high = max(item["high"] for item in previous)
                minimum_low = min(item["low"] for item in previous)
                minimum_close = min(item["close"] for item in previous)
                maximum_close = max(item["close"] for item in previous)
                price_range = max(maximum_high-minimum_close,
                                  maximum_close-minimum_low)
                self._buy_line = bar.open + .5*price_range
                self._sell_line = bar.open - .5*price_range
        else:
            self._daily["high"] = max(self._daily["high"], bar.high)
            self._daily["low"] = min(self._daily["low"], bar.low)
            self._daily["close"] = bar.close
        if self._buy_line is None:
            return []
        if (timestamp.hour, timestamp.minute) >= (14, 50):
            return self._signals(bar, 0)
        if bar.close > self._buy_line:
            return self._signals(bar, 1)
        if bar.close < self._sell_line:
            return self._signals(bar, -1)
        return []


class GridTradingStrategy(LegacyIndicatorStrategy):
    """Long-only fixed grid; a crossed layer changes the target by one lot."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self._lines = list(range(2200, 2601, 40))
        self._occupied = {line: False for line in self._lines}
        self._last_price = None

    def _indicator_signal(self):
        if self._bucket is None:
            return None
        price = self._bucket["close"]
        prior = self._last_price
        self._last_price = price
        if prior is None or price <= 0:
            return None
        target = max(0, self.position.net_volume)
        if price >= 2600:
            for line in self._lines:
                self._occupied[line] = False
            return 0 if target else None
        for index, line in enumerate(self._lines):
            if prior > line and price <= line and not self._occupied[line] and target < 10:
                target = min(target+self.volume, 10)
                self._occupied[line] = True
            if prior < line and price >= line and index > 0 and self._occupied[self._lines[index-1]]:
                target = max(target-self.volume, 0)
                self._occupied[self._lines[index-1]] = False
        return target

    def _signals(self, bar, target):
        if target is None:
            return []
        if self.direction == "short":
            target = 0
        current = int(self.position.net_volume)
        if target == current:
            return []
        signals = []
        if current < 0:
            signals.append(replace(self._signal(bar, 1, OFFSET_CLOSE, target),
                                   volume_hint=abs(current)))
            current = 0
        if target < current:
            signals.append(replace(self._signal(bar, -1, OFFSET_CLOSE, target),
                                   volume_hint=current-target))
        elif target > current:
            signals.append(replace(self._signal(bar, 1, OFFSET_OPEN, target),
                                   volume_hint=target-current))
        return signals


class OpeningRangeStrategy(LegacyIndicatorStrategy):
    """One trade per date from the first thirty minutes of the day session."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self._day = None
        self._range_high = self._range_low = None
        self._confirmed = self._traded = False

    def on_bar(self, bar, snapshot):
        del snapshot
        now = pd.Timestamp(bar.timestamp)
        if now.date() != self._day:
            self._day = now.date()
            self._range_high = self._range_low = None
            self._confirmed = self._traded = False
        clock = (now.hour, now.minute)
        if clock >= (14, 45):
            return self._signals(bar, 0)
        if (9, 30) <= clock < (10, 0):
            self._range_high = bar.high if self._range_high is None else max(self._range_high, bar.high)
            self._range_low = bar.low if self._range_low is None else min(self._range_low, bar.low)
            return []
        if clock >= (10, 0) and not self._confirmed:
            self._confirmed = self._range_high is not None
            return []
        if self._confirmed and not self._traded and self.position.net_volume == 0:
            if bar.close > self._range_high:
                if self.direction == "short":
                    return []
                self._traded = True
                return self._signals(bar, 1)
            if bar.close < self._range_low:
                if self.direction == "long":
                    return []
                self._traded = True
                return self._signals(bar, -1)
        return []


class MultiperiodMAStrategy(LegacyIndicatorStrategy):
    """Keep the source's daily, hourly and 15-minute confirmation streams."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self._day_key = self._hour_key = self._quarter_key = None
        self._day_close = self._hour_close = self._quarter_close = None
        self._days = deque(maxlen=30)
        self._hours = deque(maxlen=30)
        self._quarters = deque(maxlen=30)

    @staticmethod
    def _cross(values, fast=5, slow=20):
        if len(values) < slow+1:
            return 0
        previous_fast = sum(values[-fast-1:-1]) / fast
        previous_slow = sum(values[-slow-1:-1]) / slow
        current_fast = sum(values[-fast:]) / fast
        current_slow = sum(values[-slow:]) / slow
        if previous_fast <= previous_slow and current_fast > current_slow:
            return 1
        if previous_fast >= previous_slow and current_fast < current_slow:
            return -1
        return 0

    def on_bar(self, bar, snapshot):
        del snapshot
        stamp = pd.Timestamp(bar.timestamp)
        day_key = pd.Timestamp(bar.tradingday).normalize()
        hour_key = stamp.floor("h")
        quarter_key = stamp.floor("15min")
        if self._day_key is None:
            self._day_key, self._hour_key, self._quarter_key = day_key, hour_key, quarter_key
            self._day_close = self._hour_close = self._quarter_close = bar.close
            return []
        if day_key != self._day_key:
            self._days.append(self._day_close)
            self._day_key = day_key
        if hour_key != self._hour_key:
            self._hours.append(self._hour_close)
            self._hour_key = hour_key
        if quarter_key != self._quarter_key:
            self._quarters.append(self._quarter_close)
            self._quarter_key = quarter_key
            target = self._cross(list(self._quarters))
            if target and len(self._days) >= 20 and len(self._hours) >= 20:
                day_up = self._days[-1] > sum(list(self._days)[-20:])/20
                day_down = self._days[-1] < sum(list(self._days)[-20:])/20
                hour_up = self._hours[-1] > sum(list(self._hours)[-20:])/20
                hour_down = self._hours[-1] < sum(list(self._hours)[-20:])/20
                if target == 1 and day_up and hour_up:
                    signals = self._signals(bar, 1)
                elif target == -1 and day_down and hour_down:
                    signals = self._signals(bar, -1)
                else:
                    signals = self._signals(bar, 0)
            else:
                signals = []
        else:
            signals = []
        self._day_close = self._hour_close = self._quarter_close = bar.close
        return signals
