"""Shared adapter for the converted TqSdk indicator examples.

The original examples use TqSdk's TargetPosTask.  This module keeps their
signal intent while exposing the local CTA Strategy contract: minute bars are
aggregated to the selected timeframe and each signal targets one position.
Individual strategy packages only declare the indicator family and defaults.
"""
from __future__ import annotations

import math
from collections import deque

import pandas as pd

from framework import (
    Bar, Fill, OFFSET_CLOSE, OFFSET_OPEN, ORDER_MARKET, SIGNAL_ENTRY,
    SIGNAL_EXIT, Signal, Strategy as BaseStrategy,
)
from framework.snapshot import Snapshot


class LegacyIndicatorStrategy(BaseStrategy):
    """Runnable baseline adapter for the converted TqSdk examples."""

    REQUIRED_UNIVERSE = "self"
    # These converted packages intentionally consume one Bar stream only.
    # Cross-sectional/hedge packages are kept separate until a portfolio data
    # contract is added to the engine.
    SINGLE_SYMBOL = True
    SESSION_NAMES = ["全天"]
    SUPPORTS_BATCH_PREBUILD = False
    ALGORITHM = "ma_cross"
    DEFAULT_FAST = 5
    DEFAULT_SLOW = 20
    DEFAULT_SIGNAL = 9
    DEFAULT_VOLUME = 1

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self.timeframe = str(self.params.get("timeframe", "1h")).lower()
        self.direction = str(self.params.get("direction", "both")).lower()
        self.fast = int(self.params.get("fast_period", self.DEFAULT_FAST))
        self.slow = int(self.params.get("slow_period", self.DEFAULT_SLOW))
        self.signal_period = int(self.params.get("signal_period", self.DEFAULT_SIGNAL))
        self.volume = max(1, int(self.params.get("volume", self.DEFAULT_VOLUME)))
        if self.timeframe not in {"15m", "1h", "1d"}:
            raise ValueError("timeframe must be 15m, 1h or 1d")
        if self.direction not in {"long", "short", "both"}:
            raise ValueError("direction must be long, short or both")
        if not 0 < self.fast < self.slow:
            raise ValueError("fast_period must be smaller than slow_period")
        self._bucket_start: pd.Timestamp | None = None
        self._bucket: dict[str, float] | None = None
        self._closes: deque[float] = deque(maxlen=max(self.slow * 3, 200))
        self._volumes: deque[float] = deque(maxlen=max(self.slow * 3, 200))
        self._previous: float | None = None

    def _bucket_key(self, timestamp: pd.Timestamp) -> pd.Timestamp:
        if self.timeframe == "1d":
            return timestamp.normalize()
        minutes = 15 if self.timeframe == "15m" else 60
        epoch = int(timestamp.value // 60_000_000_000)
        return pd.Timestamp((epoch - epoch % minutes) * 60_000_000_000)

    def _start(self, bar: Bar, key: pd.Timestamp) -> None:
        self._bucket_start = key
        self._bucket = {"open": float(bar.open), "high": float(bar.high),
                        "low": float(bar.low), "close": float(bar.close),
                        "volume": float(bar.volume), "oi": float(bar.oi),
                        "tradingday": pd.Timestamp(bar.tradingday).normalize()}

    def _add(self, bar: Bar) -> None:
        if self._bucket is None:
            return
        self._bucket["high"] = max(self._bucket["high"], float(bar.high))
        self._bucket["low"] = min(self._bucket["low"], float(bar.low))
        self._bucket["close"] = float(bar.close)
        self._bucket["volume"] += float(bar.volume)
        self._bucket["oi"] = float(bar.oi)
        self._bucket["tradingday"] = pd.Timestamp(bar.tradingday).normalize()

    @staticmethod
    def _ema(value: float, previous: float | None, period: int) -> float:
        if previous is None:
            return value
        alpha = 2.0 / (period + 1.0)
        return alpha * value + (1.0 - alpha) * previous

    def _indicator_signal(self) -> int | None:
        if self._bucket is None:
            return None
        close = float(self._bucket["close"])
        if not math.isfinite(close) or close <= 0:
            return None
        self._closes.append(close)
        self._volumes.append(float(self._bucket["volume"]))
        values = list(self._closes)
        if len(values) < self.slow:
            return None
        fast = self.fast
        slow = self.slow
        algo = self.ALGORITHM
        target_value: float | None = None
        if algo == "macd":
            ef = self._ema(close, getattr(self, "_ema_fast", None), fast)
            es = self._ema(close, getattr(self, "_ema_slow", None), slow)
            dif = ef - es
            dea = self._ema(dif, getattr(self, "_dea", None), self.signal_period)
            self._ema_fast, self._ema_slow, self._dea = ef, es, dea
            target_value = dif - dea
        elif algo == "kdj":
            # Standard KDJ: RSV -> smoothed K/D, with J=3K-2D.
            window = values[-self.signal_period:]
            highest = max(window)
            lowest = min(window)
            rsv = (close - lowest) / (highest - lowest) * 100 if highest > lowest else 50.0
            k = self._ema(rsv, getattr(self, "_kdj_k", None), 3)
            d = self._ema(k, getattr(self, "_kdj_d", None), 3)
            self._kdj_k, self._kdj_d = k, d
            target_value = k - d
        elif algo in {"boll_reversion", "zscore", "rsi_reversion"}:
            window = values[-slow:]
            mean = sum(window) / len(window)
            std = (sum((v - mean) ** 2 for v in window) / len(window)) ** 0.5
            z = (close - mean) / std if std > 0 else 0.0
            target_value = -z if algo != "boll_reversion" else -z
        elif algo in {"breakout", "channel"}:
            prior = values[-slow:-1]
            if not prior:
                return None
            target_value = 1.0 if close > max(prior) else (-1.0 if close < min(prior) else 0.0)
        elif algo == "vwap":
            window = values[-slow:]
            vols = list(self._volumes)[-len(window):]
            total = sum(vols)
            vwap = sum(p * v for p, v in zip(window, vols)) / total if total > 0 else sum(window) / len(window)
            target_value = close - vwap
        elif algo == "volume_trend":
            # Single-product OBV-style money-flow trend.  This keeps the
            # volume/price examples meaningful without requiring peer symbols.
            previous_close = values[-2] if len(values) >= 2 else close
            flow = getattr(self, "_volume_flow", 0.0)
            flow += float(self._bucket["volume"]) if close >= previous_close else -float(self._bucket["volume"])
            self._volume_flow = flow
            fast_flow = getattr(self, "_fast_flow", None)
            slow_flow = getattr(self, "_slow_flow", None)
            self._fast_flow = self._ema(flow, fast_flow, fast)
            self._slow_flow = self._ema(flow, slow_flow, slow)
            target_value = self._fast_flow - self._slow_flow
        else:
            target_value = sum(values[-fast:]) / fast - sum(values[-slow:]) / slow
        previous = self._previous
        self._previous = target_value
        if previous is None:
            return None
        if algo in {"breakout", "channel"}:
            return int(target_value) if target_value else None
        if previous <= 0 < target_value:
            return 1
        if previous >= 0 > target_value:
            return -1
        return None

    def _signal(self, bar: Bar, direction: int, offset: str, target: int) -> Signal:
        return Signal(
            symbol=bar.symbol, action_datetime=bar.timestamp, bar_datetime=bar.timestamp,
            signal_kind=SIGNAL_ENTRY if offset == OFFSET_OPEN else SIGNAL_EXIT,
            direction=direction, offset=offset, order_type=ORDER_MARKET,
            session="全天", price=float(bar.close),
            volume_hint=self.volume if offset == OFFSET_OPEN else abs(int(self.position.net_volume)),
            client_order_id=self.new_client_order_id("LEGACY"),
            tag=f"{self.strategy_id}_{'long' if target > 0 else 'short'}",
        )

    def _signals(self, bar: Bar, cross: int | None) -> list[Signal]:
        if cross is None:
            return []
        target = cross
        if self.direction == "long" and target < 0:
            target = 0
        elif self.direction == "short" and target > 0:
            target = 0
        current = int(self.position.net_volume)
        current_sign = 0 if current == 0 else (1 if current > 0 else -1)
        if current_sign == target:
            return []
        signals = []
        if current:
            signals.append(self._signal(bar, -current_sign, OFFSET_CLOSE, cross))
        if target:
            signals.append(self._signal(bar, target, OFFSET_OPEN, cross))
        return signals

    def on_bar(self, bar: Bar, snapshot: Snapshot) -> list[Signal]:
        del snapshot
        key = (pd.Timestamp(bar.tradingday).normalize()
               if self.timeframe == "1d" else self._bucket_key(pd.Timestamp(bar.timestamp)))
        if self._bucket_start is None:
            self._start(bar, key)
            return []
        if key == self._bucket_start:
            self._add(bar)
            return []
        cross = self._indicator_signal()
        self._start(bar, key)
        return self._signals(bar, cross)

    def on_fill(self, fill: Fill) -> None:
        super().on_fill(fill)
