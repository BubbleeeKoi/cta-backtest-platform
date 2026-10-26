"""
jerome/features.py  ——  滚动指标累加器

- ``IndicatorWindow``  封装 mid (close 均值) + 短/长 ATR + vol_ratio 的滚动状态

True Range 定义：``max(high - low, |high - prev_close|, |low - prev_close|)``；
首根 bar 无 prev_close 时退化为 ``high - low``。
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from framework import Bar

from .params import StrategyParams


class IndicatorWindow:
    """滚动指标窗口：close 均值 mid + 短/长 ATR + vol_ratio。

    预热段（on_init）与真增量（on_bar）走同一个 ``update`` 入口，保证两端
    指标序列一致。
    """

    __slots__ = ("_params", "_closes", "_tr_short", "_tr_long", "_prev_close")

    def __init__(self, params: StrategyParams):
        self._params = params
        self._closes:   Deque[float] = deque(maxlen=params.mid_lookback_bars)
        self._tr_short: Deque[float] = deque(maxlen=params.atr_short)
        self._tr_long:  Deque[float] = deque(maxlen=params.atr_long)
        self._prev_close: Optional[float] = None

    # ── 推进 ──────────────────────────────────────────────────────────

    def update(self, bar: Bar) -> None:
        """喂入一根新 bar。"""
        close = float(bar.close)
        high = float(bar.high)
        low = float(bar.low)
        if self._prev_close is not None:
            tr = max(
                high - low,
                abs(high - self._prev_close),
                abs(low - self._prev_close),
            )
        else:
            tr = high - low
        self._tr_short.append(tr)
        self._tr_long.append(tr)
        self._closes.append(close)
        self._prev_close = close

    # ── 查询 ──────────────────────────────────────────────────────────

    @property
    def mid(self) -> Optional[float]:
        """最近 ``mid_lookback_bars`` 根 close 的均值；未灌满则返回 None。"""
        if len(self._closes) < self._params.mid_lookback_bars:
            return None
        return sum(self._closes) / len(self._closes)

    @property
    def short_atr(self) -> float:
        return (sum(self._tr_short) / len(self._tr_short)) if self._tr_short else 0.0

    @property
    def long_atr(self) -> float:
        return (sum(self._tr_long) / len(self._tr_long)) if self._tr_long else 0.0

    @property
    def vol_ratio(self) -> float:
        """``ATR_short / ATR_long``；长 ATR 未灌满或为 0 时退化为 1.0。"""
        long_atr = self.long_atr
        if long_atr <= 0:
            return 1.0
        return self.short_atr / long_atr


__all__ = ["IndicatorWindow"]
