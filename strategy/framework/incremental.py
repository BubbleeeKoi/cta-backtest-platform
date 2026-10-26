"""
framework/incremental.py  ——  跨策略共享的真增量滚动算子

提供 O(1) / O(log N) 的滚动统计算子，行为与 ``pd.Series.rolling(...).agg``
（``skip-NaN``、``min_periods`` 语义）等价。

策略包之间**不应**互相 sibling import 此类基础算子：共用增量算子统一在本
模块声明，策略需要时直接从 ``framework.incremental`` 导入。

实现说明
========
``ddof=1`` rolling std 与 pandas ``rolling.std(ddof=1)`` 在浮点舍入误差范围
内一致；``rolling quantile`` 与 numpy / pandas 默认 ``linear`` interpolation
完全一致。
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

import numpy as np
from sortedcontainers import SortedList


class IncrementalRollingMean:
    """O(1) rolling mean，与 ``pd.Series.rolling(window, min_periods).mean()`` 等价。

    pandas 行为
    ----------
    - skip-NaN：NaN 占窗口位但不参与求和；分母 = non-NaN 个数。
    - ``min_periods``：non-NaN 数 < min_periods → 输出 NaN，否则输出 sum / n_non_nan。
    """

    __slots__ = ("_window", "_min_periods", "_buf", "_sum", "_n_non_nan")

    def __init__(self, window: int, min_periods: Optional[int] = None) -> None:
        self._window = int(window)
        self._min_periods = int(min_periods) if min_periods is not None else int(window)
        self._buf: Deque[float] = deque(maxlen=self._window)
        self._sum: float = 0.0
        self._n_non_nan: int = 0

    def update(self, x: float) -> float:
        if len(self._buf) >= self._window:
            old = self._buf[0]
            if old == old:  # not NaN
                self._sum -= old
                self._n_non_nan -= 1
        self._buf.append(x)
        if x == x:  # not NaN
            self._sum += x
            self._n_non_nan += 1
        if self._n_non_nan < self._min_periods:
            return float("nan")
        return self._sum / self._n_non_nan


class IncrementalRollingStd:
    """O(1) rolling std（ddof=1），与 ``pd.Series.rolling(window, min_periods).std(ddof=1)`` 等价。

    数值精度
    --------
    使用经典 ``var = (sum_sq - n·mean²) / (n-1)`` 公式。理论上有 catastrophic
    cancellation 风险，但对布林带这类"邻近均值的价格序列"，差异在 1e-10 量级
    内（pandas 内部 Kahan 求和减少误差）；用 ``-1e-12 < var < 0: var = 0`` 兜底
    负数舍入。
    """

    __slots__ = ("_window", "_min_periods", "_buf", "_sum", "_sum_sq", "_n_non_nan")

    def __init__(self, window: int, min_periods: Optional[int] = None) -> None:
        self._window = int(window)
        self._min_periods = int(min_periods) if min_periods is not None else int(window)
        self._buf: Deque[float] = deque(maxlen=self._window)
        self._sum: float = 0.0
        self._sum_sq: float = 0.0
        self._n_non_nan: int = 0

    def update(self, x: float) -> float:
        if len(self._buf) >= self._window:
            old = self._buf[0]
            if old == old:
                self._sum -= old
                self._sum_sq -= old * old
                self._n_non_nan -= 1
        self._buf.append(x)
        if x == x:
            self._sum += x
            self._sum_sq += x * x
            self._n_non_nan += 1
        if self._n_non_nan < self._min_periods or self._n_non_nan < 2:
            return float("nan")
        n = self._n_non_nan
        mean = self._sum / n
        var = (self._sum_sq - n * mean * mean) / (n - 1)
        if var < 0.0 and var > -1e-12:
            var = 0.0
        return float(np.sqrt(var)) if var >= 0.0 else float("nan")


class IncrementalRollingQuantile:
    """O(log N) rolling quantile（linear interpolation），与 pandas ``rolling.quantile`` 等价。

    实现要点
    --------
    - ``deque(maxlen=window)`` 维护原始顺序窗口；``SortedList`` 维护当前 non-NaN
      值的有序视图。
    - 每根 bar：popleft 最老值 → SortedList.remove → append 新值 → SortedList.add。
      二者都是 O(log N) （SortedList 基于 skip list-like 平衡树结构）。
    - quantile 计算：``idx = (n-1) * q``；``lo = floor(idx)``；
      ``out = sorted[lo] + frac * (sorted[lo+1] - sorted[lo])`` ——与 numpy / pandas
      默认 ``linear`` interpolation 完全一致。
    """

    __slots__ = ("_window", "_min_periods", "_q", "_buf", "_sorted")

    def __init__(self, window: int, q: float, min_periods: Optional[int] = None) -> None:
        self._window = int(window)
        self._min_periods = int(min_periods) if min_periods is not None else int(window)
        self._q = float(q)
        self._buf: Deque[float] = deque(maxlen=self._window)
        self._sorted: SortedList = SortedList()

    def update(self, x: float) -> float:
        if len(self._buf) >= self._window:
            old = self._buf[0]
            if old == old:
                self._sorted.remove(old)
        self._buf.append(x)
        if x == x:
            self._sorted.add(x)
        n = len(self._sorted)
        if n < self._min_periods:
            return float("nan")
        if n == 1:
            return self._sorted[0]
        idx = (n - 1) * self._q
        lo = int(idx)
        if lo >= n - 1:
            return self._sorted[n - 1]
        frac = idx - lo
        return self._sorted[lo] + frac * (self._sorted[lo + 1] - self._sorted[lo])


__all__ = [
    "IncrementalRollingMean",
    "IncrementalRollingStd",
    "IncrementalRollingQuantile",
]
