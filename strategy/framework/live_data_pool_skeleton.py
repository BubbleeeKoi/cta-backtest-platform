"""
framework/live_data_pool_skeleton.py  ——  实盘 DataPool 骨架（供 IT 填充实现）

这不是一个可直接运行的实现，而是一份"骨架 + 注释"，定义了所有方法在
实盘场景下应满足的语义。IT 根据接入的实盘行情服务（CTP / 自研 tick
中枢 / 数据回放）把 TODO 处填上即可。

骨架仅继承 ``DataPool``（基础协议），不实现 ``BatchDataPool``（回测扩展协议）。
策略代码两端共用同一份；批量路径通过 ``isinstance(data_pool, BatchDataPool)``
自动分流，实盘端永远落到流式路径。

──────────────────────────────────────────────────────────────────────────────
方法重要性分级
──────────────────────────────────────────────────────────────────────────────
最常用的实盘 API:
    - get_minute_bars        (拉取截至 as_of 的 N 根分钟 bar)

仅批量预算路径调用、实盘不需要的 API（仅 BatchDataPool 拥有，本骨架不实现）:
    - get_all_bars / get_frames_snapshot

引擎 / 组合层 / 报表层会触达（与具体策略无关）:
    - list_universe
    - sector_of
    - symbols_in_sector
    - contract_info
    - get_session_bars       (按 tradingday + 时段切片；按策略需求实现)
    - get_daily_panel        (日频面板；按策略需求实现)

──────────────────────────────────────────────────────────────────────────────
关于"因果安全"（DataPool 协议核心约束）
──────────────────────────────────────────────────────────────────────────────
所有"按 as_of / tradingday 切片"的查询接口必须：
    1. 不返回 actiontime > as_of 的任何 bar；
    2. 不返回 tradingday > as_of_td 的任何聚合；
    3. 同一 (symbol, as_of, n_bars) 查询的返回值必须可重复（无随机性）。

实盘场景下"当前时刻"由行情推进决定。建议在内部维护一个"已收到的最后
一根完成 bar 的时间戳"，as_of 必须 ≤ 该时间戳。

──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

from .data_pool import DataPool


class LiveDataPoolSkeleton(DataPool):
    """实盘 DataPool 骨架。IT 在此基础上 fork / 继承，填充 TODO 即可。"""

    def __init__(
        self,
        future_list: pd.DataFrame,
        industry_map: pd.DataFrame,
        # 例如订阅行情的 client、行情缓存 store、合约表等
    ) -> None:
        self._future_list = future_list
        self._industry_map = industry_map
        # TODO: 持有实盘行情服务的句柄 / 本地行情缓存
        # self._tick_client = ...
        # self._minute_cache: Dict[str, pd.DataFrame] = {}

    # ──────────────────────────────────────────────────────────────────
    # 元数据（建议直接照 BacktestDataPool 的实现搬过来）
    # ──────────────────────────────────────────────────────────────────

    def list_universe(self) -> List[str]:
        """返回 future_list 中 trade=True 的全部品种代码。"""
        # 参考 BacktestDataPool 实现：
        #   return list(self._future_list[self._future_list["trade"] == True]["symbol"])
        raise NotImplementedError("TODO: 返回 trade=True 品种代码列表")

    def sector_of(self, symbol: str) -> str:
        """根据 industry_map 查询品种所属板块。"""
        raise NotImplementedError("TODO: 查 industry_map[symbol] -> sector")

    def symbols_in_sector(
        self, sector: str, exclude: Optional[List[str]] = None
    ) -> List[str]:
        """返回某板块内全部品种，可剔除指定品种。"""
        raise NotImplementedError(
            "TODO: 过滤 industry_map.sector == sector，再剔除 exclude"
        )

    def contract_info(self, symbol: str) -> dict:
        """
        返回 future_list 中该品种一行的 dict。

        必须包含的键：
            symbol, point (合约乘数), tick_size, sector, exchange,
            commission_per_unit / commission_rate（用于交易成本估算）
        """
        raise NotImplementedError("TODO: 取 future_list[symbol] 一行 -> dict")

    # ──────────────────────────────────────────────────────────────────
    # 数据访问（实盘必须实现：runtime on_bar 路径会调用）
    # ──────────────────────────────────────────────────────────────────

    def get_minute_bars(
        self,
        symbol: str,
        as_of: pd.Timestamp,
        n_bars: int,
    ) -> pd.DataFrame:
        """
        取截至 as_of（含）的最近 n_bars 根 1 分钟 bar。

        实盘实现要点：
        1. as_of 必须严格 ≤ 已收到的最后一根完成 bar 的时间，否则需要等待 /
           抛 ValueError，绝不能返回 actiontime > as_of 的行（因果安全）。
        2. 返回 DataFrame index = DatetimeIndex(actiontime)；columns 至少包含
           open / high / low / close / volume / oi / tradingday。
        3. 不足 n_bars 时返回全部可得行，不做填充；最早不足时返回空 DataFrame。

        ⚠️ 这是 on_bar 路径下最频繁调用的方法（目标品种 + 同板块 peer 都会
           走这条路径）。性能敏感，建议本地维护近 N 根 bar 的滚动缓存，避免
           每次都 round-trip 行情服务。
        """
        raise NotImplementedError(
            "TODO: 实盘行情服务 / 本地 bar 缓存查询；保证因果安全"
        )

    def get_session_bars(
        self,
        symbol: str,
        tradingday: pd.Timestamp,
        session_start: str,
        session_end: str,
    ) -> pd.DataFrame:
        """
        取某交易日某时段（如 "09:00" → "09:30"）的全部 bar。

        非所有策略都需要本方法，未用到的策略可保留 NotImplementedError。
        """
        raise NotImplementedError(
            "TODO：按 tradingday + session 窗口切片返回 bar"
        )

    def get_daily_panel(
        self,
        metric: str,
        symbols: List[str],
        as_of_td: pd.Timestamp,
        n_days: int,
    ) -> pd.DataFrame:
        """
        日频面板。非所有策略都需要本方法，未用到的策略可保留 NotImplementedError。
        """
        raise NotImplementedError(
            "TODO：日频聚合面板（close / volume / oi / high / low / open）"
        )
