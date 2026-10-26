"""
core/data_pool.py  ——  BacktestDataPool 实现

回测侧 DataPool：
    - 启动时按 universe 一次性加载全部品种到内存
    - 每次访问都基于 as_of 做 boolean 切片，保证因果安全
    - 提供 minute / session / daily 三类查询

性能注意:
    - 单品种 ~5 年分钟数据约 100~200 万行；30 个品种约 5GB 内存
    - 切片性能依赖 sort + searchsorted，O(log n)；可承受策略每根 bar 多次查询

数据源解耦
    具体"从哪里 / 怎么加载 minute bar"由 ``MinuteBarSource`` 子类负责，
    构造时通过 ``source`` 注入。常用 source:
      - ``HDF5IndexSource``    研究回测（商品指数 HDF5）
      - ``LiveArchiveSource``  对账回测（与实盘同源的归档 bar）

    为兼容旧调用方，仍支持 ``data_dir=...`` 直接构造（等价于注入
    ``HDF5IndexSource(data_dir)``）。
"""
from __future__ import annotations

from datetime import time
from typing import Dict, List, Optional

import pandas as pd

from tqdm import tqdm

from data_sources import HDF5IndexSource, MinuteBarSource
from framework.data_pool import BatchDataPool

from .data_loader import (
    load_future_list,
    load_industry_map,
)


class BacktestDataPool(BatchDataPool):
    """
    回测侧 DataPool（实现 BatchDataPool，因此自动满足 DataPool）。

    构造（推荐：注入 source）:
        from data_sources import HDF5IndexSource
        pool = BacktestDataPool(
            symbols       = ["RB", "MA", "CU"],
            source        = HDF5IndexSource(data_dir="/path/to/h5"),
            future_list   = pd.DataFrame,
            industry_map  = dict[symbol, sector],
        )

    向后兼容（旧入参 ``data_dir``）:
        pool = BacktestDataPool(
            symbols       = [...],
            data_dir      = "/path/to/h5",  # 自动包成 HDF5IndexSource
            future_list   = ...,
            industry_map  = ...,
        )
    """

    def __init__(
        self,
        symbols: List[str],
        source: Optional[MinuteBarSource] = None,
        future_list: Optional[pd.DataFrame] = None,
        industry_map: Optional[Dict[str, str]] = None,
        data_dir: Optional[str] = None,  # 向后兼容：等价于 source=HDF5IndexSource(data_dir)
    ) -> None:
        if source is None:
            if not data_dir:
                raise ValueError(
                    "BacktestDataPool 至少要传 source= 或 data_dir= 之一"
                )
            source = HDF5IndexSource(data_dir=data_dir)

        self.source       = source
        # ``data_dir`` 字段保留作为可读元信息；新代码应改用 ``source.describe()``。
        self.data_dir     = data_dir or source.describe()
        self.future_list  = future_list if future_list is not None else load_future_list()
        self.industry_map = industry_map if industry_map is not None else load_industry_map()

        # 加载所有品种到内存
        self._symbols: List[str] = []
        self._frames: Dict[str, pd.DataFrame] = {}
        iterator = tqdm(symbols, desc="加载行情", ncols=80) if len(symbols) > 1 else symbols
        for sym in iterator:
            df = source.load(sym)
            if df is None or df.empty:
                continue
            self._frames[sym] = df
            self._symbols.append(sym)

        # 板块 → 品种 反向索引
        self._sector_to_symbols: Dict[str, List[str]] = {}
        for sym in self._symbols:
            sec = self.sector_of(sym)
            self._sector_to_symbols.setdefault(sec, []).append(sym)

    # ── 元数据 ────────────────────────────────────────────────────────

    def list_universe(self) -> List[str]:
        return list(self._symbols)

    def sector_of(self, symbol: str) -> str:
        return self.industry_map.get(symbol, "Unknown")

    def symbols_in_sector(
        self,
        sector: str,
        exclude: Optional[List[str]] = None,
    ) -> List[str]:
        symbols = self._sector_to_symbols.get(sector, [])
        if exclude:
            excl = set(exclude)
            symbols = [s for s in symbols if s not in excl]
        return list(symbols)

    def contract_info(self, symbol: str) -> dict:
        if symbol in self.future_list.index:
            row = self.future_list.loc[symbol]
            d = row.to_dict()
            d["product"] = symbol
            return d
        return {"product": symbol}

    # ── 数据访问 ──────────────────────────────────────────────────────

    def get_minute_bars(
        self,
        symbol: str,
        as_of: pd.Timestamp,
        n_bars: int,
    ) -> pd.DataFrame:
        df = self._frames.get(symbol)
        if df is None:
            return pd.DataFrame()
        # searchsorted 返回 as_of 之后第一个位置；切片 [:pos] 含等于 as_of 的
        pos = df.index.searchsorted(as_of, side="right")
        if pos == 0:
            return pd.DataFrame()
        start = max(0, pos - n_bars)
        return df.iloc[start:pos]

    def get_all_bars(self, symbol: str, copy: bool = True) -> pd.DataFrame:
        df = self._frames.get(symbol)
        if df is None:
            return pd.DataFrame()
        return df.copy() if copy else df

    def get_frames_snapshot(
        self,
        symbols: List[str],
        columns: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for sym in symbols:
            df = self._frames.get(sym)
            if df is None or df.empty:
                continue
            out[sym] = df[columns] if columns is not None else df
        return out

    def get_session_bars(
        self,
        symbol: str,
        tradingday: pd.Timestamp,
        session_start: str,
        session_end: str,
    ) -> pd.DataFrame:
        df = self._frames.get(symbol)
        if df is None:
            return pd.DataFrame()
        # 按 tradingday 切片
        td_norm = pd.Timestamp(tradingday).normalize()
        mask = df["tradingday"] == td_norm
        day_df = df.loc[mask]
        if day_df.empty:
            return day_df
        # 按时段时间切片
        start_t = _parse_hhmm(session_start)
        end_t   = _parse_hhmm(session_end)
        return day_df.between_time(start_t, end_t, inclusive="both")

    def get_daily_panel(
        self,
        metric: str,
        symbols: List[str],
        as_of_td: pd.Timestamp,
        n_days: int,
    ) -> pd.DataFrame:
        """
        多品种日频面板。metric 选 close / volume / oi / open / high / low。

        实现：对每个 symbol 按 tradingday groupby 取聚合值。close 取 last,
        volume 取 sum, oi 取 last。
        """
        agg_map = {
            "open":   "first",
            "high":   "max",
            "low":    "min",
            "close":  "last",
            "volume": "sum",
            "oi":     "last",
        }
        if metric not in agg_map:
            raise ValueError(f"未知 metric: {metric}（可选: {list(agg_map)}）")

        as_of_norm = pd.Timestamp(as_of_td).normalize()
        cols: Dict[str, pd.Series] = {}
        for sym in symbols:
            df = self._frames.get(sym)
            if df is None or metric not in df.columns:
                continue
            mask = df["tradingday"] <= as_of_norm
            sub = df.loc[mask]
            if sub.empty:
                continue
            daily = sub.groupby("tradingday")[metric].agg(agg_map[metric])
            cols[sym] = daily.tail(n_days)

        if not cols:
            return pd.DataFrame()
        return pd.DataFrame(cols).sort_index()


def _parse_hhmm(hhmm: str) -> time:
    """'HH:MM' → datetime.time"""
    h, m = hhmm.split(":")
    return time(int(h), int(m))
