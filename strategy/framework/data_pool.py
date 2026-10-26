"""
framework/data_pool.py  ——  DataPool 抽象接口

策略通过 self.data_pool 获取跨品种数据。实盘和回测各自实现，但接口签名
必须完全一致，从而策略代码两端共用同一份。

两级协议：
    DataPool       基础协议（实盘必须实现）。仅承诺因果安全的"过去 N 根 bar"
                   / "某交易日某时段" 等 as_of 切片查询。
    BatchDataPool  回测扩展协议（DataPool 子类，多 2 个方法）。承诺
                   "返回 self 全量历史 DataFrame"、"批量取多品种全量
                   DataFrame"，仅在回测内存中存储全部历史时可用。

策略侧分流：
    if isinstance(self.data_pool, BatchDataPool):  # 回测快路径
        ...
    else:                                          # 实盘流式
        ...

支持 3 类访问形态:
    1. minute 历史窗口  —— get_minute_bars()      (唐烨 / 许贺 / 高纵 用)
    2. 日频汇总面板     —— get_daily_panel()      (郝昱翔 用)
    3. 任意时段聚合     —— get_session_bars()     (王志豪用早盘)

外加元数据查询:
    sector_of() / symbols_in_sector() / list_universe()
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

import pandas as pd

__all__ = ["DataPool", "BatchDataPool"]


class DataPool(ABC):
    """
    跨品种数据池基础协议（实盘必须实现）。

    回测：core/data_pool.py 中的 BacktestDataPool 提供实现（其继承自
          BatchDataPool，自动满足本协议）
    实盘：实盘项目自行实现一个 LiveDataPool（订阅行情服务）

    所有方法都是因果安全的：基于 as_of 参数，绝不返回未来数据。
    """

    # ──────────────────────────────────────────────────────────────────
    # 元数据
    # ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def list_universe(self) -> List[str]:
        """当前可访问的所有品种代码（按 future_list.csv 中 trade=True 的子集）。"""

    @abstractmethod
    def sector_of(self, symbol: str) -> str:
        """返回品种所属板块代码（由 industry_map.csv 决定）。"""

    @abstractmethod
    def symbols_in_sector(self, sector: str, exclude: Optional[List[str]] = None) -> List[str]:
        """返回某板块内全部品种。可选剔除自身或其它品种。"""

    @abstractmethod
    def contract_info(self, symbol: str) -> dict:
        """返回 future_list.csv 中该品种一行的 dict（含 point / tick_size / sector / ...）。"""

    # ──────────────────────────────────────────────────────────────────
    # 数据访问
    # ──────────────────────────────────────────────────────────────────

    @abstractmethod
    def get_minute_bars(
        self,
        symbol: str,
        as_of: pd.Timestamp,
        n_bars: int,
    ) -> pd.DataFrame:
        """
        取某品种截至 as_of（含）的最近 n_bars 根 1 分钟 bar。

        返回 DataFrame:
            index   = DatetimeIndex (actiontime)
            columns = open / high / low / close / volume / oi / tradingday

        若数据不足 n_bars，返回当前可得的全部行（不补齐）。
        若 as_of 早于第一条 bar，返回空 DataFrame。
        """

    @abstractmethod
    def get_session_bars(
        self,
        symbol: str,
        tradingday: pd.Timestamp,
        session_start: str,
        session_end: str,
    ) -> pd.DataFrame:
        """
        取某品种某交易日某时段（如 "09:00" → "09:30"）的全部 bar。

        参数:
            tradingday    交易日（不是 actionday）
            session_start "HH:MM" 字符串，包含
            session_end   "HH:MM" 字符串，包含

        返回 DataFrame 同 get_minute_bars 格式。
        """

    @abstractmethod
    def get_daily_panel(
        self,
        metric: str,
        symbols: List[str],
        as_of_td: pd.Timestamp,
        n_days: int,
    ) -> pd.DataFrame:
        """
        取多品种日频面板。

        参数:
            metric      "close" / "volume" / "oi" / "high" / "low" / "open"
            symbols     品种列表
            as_of_td    截至交易日（含）
            n_days      最近多少个交易日

        返回 DataFrame:
            index   = tradingday
            columns = symbol 子集
            values  = 日频聚合值（close = 日末值；volume / oi = 日聚合 sum / 日末值）
        """


class BatchDataPool(DataPool):
    """
    回测扩展协议：在 DataPool 之上增加"全量历史"批量访问能力。

    存在意义：批量预算路径需要一次性拿到完整历史
    DataFrame 才能做矢量化决策。这种"返回全量未来"的能力在实盘场景下
    既不存在也不可能存在（违反因果安全），因此独立成扩展协议，让
    策略代码通过 ``isinstance(data_pool, BatchDataPool)`` 安全分流。

    实盘 LiveDataPool 绝不实现此协议；任何依赖 BatchDataPool 的策略
    路径在实盘端会自动失效（isinstance 返回 False）。
    """

    @abstractmethod
    def get_all_bars(self, symbol: str, copy: bool = True) -> pd.DataFrame:
        """
        返回该品种全部历史 minute bar（仅回测可用）。

        参数:
            copy=True   默认，返回 DataFrame 拷贝（防止策略侧误改污染池内数据）
            copy=False  返回原始引用（read-only 调用方专用，避免不必要的内存复制）
        """

    @abstractmethod
    def get_frames_snapshot(
        self,
        symbols: List[str],
        columns: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        批量取多品种全量 DataFrame，用于把数据打包到子进程（仅回测可用）。

        参数:
            symbols  品种列表（不存在的品种自动跳过）
            columns  仅保留指定列（None 表示全部列），用于裁剪 pickle 体积
        """
