"""Configurable moving-average crossover strategy.

Supported timeframes: 1d, 1h and 15m.
Supported directions: long, short and both.
"""

from __future__ import annotations

import math
from collections import deque

import pandas as pd

from framework import (
    Bar, Fill, OFFSET_CLOSE, OFFSET_OPEN, ORDER_MARKET, ORDER_MARKET_0905,
    SIGNAL_ENTRY, SIGNAL_EXIT, Signal, Strategy as BaseStrategy,
)
from framework.snapshot import Snapshot

from .params import DIRECTION, FAST_PERIOD, SESSION_NAME, SLOW_PERIOD, TIMEFRAME


class Strategy(BaseStrategy):
    REQUIRED_UNIVERSE = "self"
    SESSION_NAMES = [SESSION_NAME]
    SUPPORTS_BATCH_PREBUILD = False

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self.fast_period = int(self.params.get("fast_period", FAST_PERIOD))
        self.slow_period = int(self.params.get("slow_period", SLOW_PERIOD))
        self.timeframe = str(self.params.get("timeframe", TIMEFRAME)).lower()
        self.direction = str(self.params.get("direction", DIRECTION)).lower()
        if not 0 < self.fast_period < self.slow_period:
            raise ValueError("MA periods must satisfy 0 < fast_period < slow_period")
        if self.timeframe not in {"15m", "1h", "1d"}:
            raise ValueError("timeframe must be 15m, 1h or 1d")
        if self.direction not in {"long", "short", "both"}:
            raise ValueError("direction must be long, short or both")
        self._closes: deque[float] = deque(maxlen=self.slow_period)
        self._previous_spread: float | None = None
        self._bucket_start: pd.Timestamp | None = None
        self._bucket: dict[str, float] | None = None

    @property
    def _intraday_minutes(self) -> int:
        return {"15m": 15, "1h": 60}.get(self.timeframe, 0)

    @staticmethod
    def _bucket_key(timestamp: pd.Timestamp, minutes: int) -> pd.Timestamp:
        epoch_minutes = int(timestamp.value // 60_000_000_000)
        return pd.Timestamp((epoch_minutes - epoch_minutes % minutes) * 60_000_000_000)

    def _start_bucket(self, bar: Bar, key: pd.Timestamp) -> None:
        self._bucket_start = key
        self._bucket = {
            "open": float(bar.open), "high": float(bar.high),
            "low": float(bar.low), "close": float(bar.close),
            "volume": float(bar.volume),
        }

    def _add_bucket_bar(self, bar: Bar) -> None:
        if self._bucket is None:
            return
        self._bucket["high"] = max(self._bucket["high"], float(bar.high))
        self._bucket["low"] = min(self._bucket["low"], float(bar.low))
        self._bucket["close"] = float(bar.close)
        self._bucket["volume"] += float(bar.volume)

    def _consume_close(self, close: float) -> int | None:
        if not math.isfinite(close) or close <= 0:
            return None
        self._closes.append(close)
        if len(self._closes) < self.slow_period:
            return None
        values = list(self._closes)
        spread = (
            sum(values[-self.fast_period:]) / self.fast_period
            - sum(values) / self.slow_period
        )
        previous = self._previous_spread
        self._previous_spread = spread
        if previous is None:
            return None
        if previous <= 0 < spread:
            return 1
        if previous >= 0 > spread:
            return -1
        return None

    def _finish_bucket(self) -> int | None:
        if self._bucket is None:
            return None
        return self._consume_close(float(self._bucket["close"]))

    def _allowed_target(self, cross_target: int) -> int:
        if self.direction == "long":
            return 1 if cross_target == 1 else 0
        if self.direction == "short":
            return -1 if cross_target == -1 else 0
        return cross_target

    def _signal(self, bar: Bar, direction: int, offset: str,
                volume_hint: int | None, target: int) -> Signal:
        return Signal(
            symbol=bar.symbol,
            action_datetime=bar.timestamp,
            bar_datetime=bar.timestamp,
            signal_kind=SIGNAL_ENTRY if offset == OFFSET_OPEN else SIGNAL_EXIT,
            direction=direction,
            offset=offset,
            order_type=(ORDER_MARKET_0905 if self.timeframe == "1d" else ORDER_MARKET),
            session=SESSION_NAME,
            price=float(bar.close),
            volume_hint=volume_hint,
            client_order_id=self.new_client_order_id("MA"),
            tag="ma_golden_cross" if target == 1 else "ma_death_cross",
        )

    def _make_signals(self, bar: Bar, cross_target: int) -> list[Signal]:
        target = self._allowed_target(cross_target)
        current = int(self.position.net_volume)
        current_sign = 0 if current == 0 else (1 if current > 0 else -1)
        if target == current_sign:
            return []
        signals: list[Signal] = []
        if current:
            signals.append(self._signal(
                bar, -current_sign, OFFSET_CLOSE, abs(current), cross_target,
            ))
        if target:
            signals.append(self._signal(
                bar, target, OFFSET_OPEN, None, cross_target,
            ))
        return signals

    def on_bar(self, bar: Bar, snapshot: Snapshot) -> list[Signal]:
        del snapshot
        if self.timeframe == "1d":
            # 09:05 is reserved for filling prior-day orders; the other event
            # is the completed daily close used for the MA signal.
            if bar.timestamp.hour == 9 and bar.timestamp.minute == 5:
                return []
            cross_target = self._consume_close(float(bar.close))
            return self._make_signals(bar, cross_target) if cross_target else []

        key = self._bucket_key(pd.Timestamp(bar.timestamp), self._intraday_minutes)
        if self._bucket_start is None:
            self._start_bucket(bar, key)
            return []
        if key == self._bucket_start:
            self._add_bucket_bar(bar)
            return []
        # Complete the previous timeframe before starting the current one.
        cross_target = self._finish_bucket()
        self._start_bucket(bar, key)
        return self._make_signals(bar, cross_target) if cross_target else []

    def on_fill(self, fill: Fill) -> None:
        super().on_fill(fill)
