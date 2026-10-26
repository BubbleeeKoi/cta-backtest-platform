"""
framework/snapshot.py  ——  横截面 lazy 视图

策略在 on_bar(bar, snapshot) 里通过 snapshot 访问同一时间戳上其它品种的 bar。

设计要点:
    - snapshot 是 lazy 的：访问 snapshot["RB"] 时才从 data_pool 取
    - 严格按 ts（当前 bar 的 timestamp）做截面，绝不返回未来数据
    - 同时提供 sector / universe 元信息查询

HistoryView 在 on_init(history) 时传入，给出预热历史 DataFrame。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from .data_pool import DataPool
from .types import Bar


# ──────────────────────────────────────────────────────────────────────────
# Snapshot —— on_bar 第二参
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    """
    横截面 lazy 视图（仅在 on_bar 期间有效）。

    属性:
        current_symbol   当前策略实例对应的品种
        current_bar      当前 bar（与 on_bar 第一参一致，方便引用）
        ts               当前 bar 的 timestamp
        universe         可访问的品种列表（由 ``data_pool.list_universe()`` 提供）
        sector           当前品种所属板块（缓存）

    方法:
        get_bar(symbol)   取同一时刻其它品种的 bar；不存在则返回 None
        peers_in_sector(exclude_self=True)   返回当前品种所在板块的其它品种列表
    """
    current_symbol: str
    current_bar: Bar
    ts: pd.Timestamp
    universe: List[str]
    sector: str
    data_pool: DataPool

    # _bar_cache 仅在本 snapshot 生命周期内有效（一根 bar）；避免 frozen
    _bar_cache: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # dataclass 不支持 default_factory 与 frozen 同时用，这里手工初始化
        if self._bar_cache is None:
            self._bar_cache = {}

    def get_bar(self, symbol: str) -> Optional[Bar]:
        """取某品种在当前 ts 上的 bar。不在 universe 内或数据缺失返回 None。"""
        if symbol == self.current_symbol:
            return self.current_bar
        if symbol not in self.universe:
            return None
        if symbol in self._bar_cache:
            return self._bar_cache[symbol]
        bars = self.data_pool.get_minute_bars(symbol, self.ts, n_bars=1)
        if bars.empty:
            self._bar_cache[symbol] = None
            return None
        row = bars.iloc[-1]
        if row.name != self.ts:
            # 该品种在此时刻没有 bar（例如非交易时段）
            self._bar_cache[symbol] = None
            return None
        bar = Bar(
            symbol     = symbol,
            timestamp  = row.name,
            tradingday = row["tradingday"],
            open       = float(row["open"]),
            high       = float(row["high"]),
            low        = float(row["low"]),
            close      = float(row["close"]),
            volume     = float(row["volume"]),
            oi         = float(row.get("oi", 0.0)),
        )
        self._bar_cache[symbol] = bar
        return bar

    def peers_in_sector(self, exclude_self: bool = True) -> List[str]:
        """返回当前品种所在板块的其它品种（默认剔除自己）。"""
        exclude = [self.current_symbol] if exclude_self else None
        return self.data_pool.symbols_in_sector(self.sector, exclude=exclude)


# ──────────────────────────────────────────────────────────────────────────
# HistoryView —— on_init 入参
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class HistoryView:
    """
    on_init(history) 入参。

    提供：
        - own_bars       当前品种全部历史（DataFrame）
        - data_pool      访问跨品种历史

    回测：own_bars 是回测窗口之前的预热段（warmup）；warmup 长度由 runtime 配置。
    实盘：own_bars 是策略上线时从行情服务拉取的最近 N 日历史。
    """
    symbol: str
    own_bars: pd.DataFrame
    data_pool: DataPool
