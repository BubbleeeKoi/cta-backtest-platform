"""
data_sources/base.py  ——  MinuteBarSource 抽象基类

策略侧通过 ``self.data_pool`` 访问数据，DataPool 通过 ``MinuteBarSource``
访问"原始 bar 加载"。多种数据源（研究指数 / 实盘归档）只要实现本协议即可
被 ``BacktestDataPool`` 装配。

为什么要这一层
    回测要支持两类数据源：
      1. 历史研究用的商品指数 HDF5（多合约加权）
      2. 与实盘同源的 minute bar 归档（主力合约展期 / tick 合成）
    它们的加载逻辑差异很大，但提供给上层的 DataFrame schema 必须严格一致，
    才能让同一份策略代码在两类数据上都能跑、产物可对账。本基类把这条契约
    写死，新增数据源只需补一个子类。

统一 schema
    DataFrame
        index   = DatetimeIndex (actiontime, 严格升序、无重复)
        columns = open, high, low, close, volume, oi, tradingday
        dtype   = float64 (前 6 列), datetime64[ns] (tradingday)
        tradingday 跨夜归属"次日交易日"（与现有口径一致）
    缺失列可由 source 内部补 0 / 默认值；返回前必须 sort_index。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "open", "high", "low", "close", "volume", "oi", "tradingday",
)


class MinuteBarSource(ABC):
    """单品种 minute bar 加载器协议。

    实现要点:
        - ``load(symbol)`` 返回的 DataFrame 必须满足 ``REQUIRED_COLUMNS`` 全部列；
          不存在的列由 source 内部补默认值（如 ``oi=0.0``）。
        - 不存在该 symbol 时返回 ``None``（**不要**抛异常，调用方按"跳过"处理）。
        - ``list_available_symbols()`` 返回该 source 当前可加载的全部品种代码；
          不依赖 future_list，只看自家底层存储里到底有什么。
    """

    @abstractmethod
    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        """加载单品种全量 minute bar；不存在返回 None。"""

    @abstractmethod
    def list_available_symbols(self) -> List[str]:
        """枚举当前 source 实际可加载的品种代码（不是 universe）。"""

    # ── 便利方法（子类可不覆盖） ───────────────────────────────────────

    def describe(self) -> str:
        """一行可读描述，用于日志/报错提示。子类可覆盖。"""
        return type(self).__name__


def validate_schema(df: pd.DataFrame, symbol: str, source_name: str) -> pd.DataFrame:
    """校验 + 规整：补缺失列、强制升序、确保 tradingday 是 datetime64。

    供 source 子类 ``load`` 收尾调用，集中处理一次性 schema 修正。
    """
    if df is None or df.empty:
        return df

    # 补缺失列
    for col in REQUIRED_COLUMNS:
        if col not in df.columns:
            if col == "oi":
                df[col] = 0.0
            elif col == "tradingday":
                # 兜底：用 actiontime 归一化；夜盘 21:00 之后归次日须 source 自处理
                df[col] = pd.to_datetime(df.index).normalize()
            else:
                raise ValueError(
                    f"[{source_name}] symbol={symbol} 缺少必需列 {col!r}"
                )

    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    if not df["tradingday"].dtype.kind == "M":
        df["tradingday"] = pd.to_datetime(df["tradingday"])

    if not df.index.is_monotonic_increasing:
        df = df.sort_index()

    return df
