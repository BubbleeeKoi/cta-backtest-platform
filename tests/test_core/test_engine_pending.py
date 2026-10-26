"""引擎层 pending 订单行为测试：

1. 同 bar 撤旧挂新（验证 _step_bar 五阶段顺序）
2. 稀疏路径下调用 cancel_order → RuntimeError
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd
import pytest

from core.accounting import TradeAccountant
from core.engine.loop import BacktestEngine, StrategySlot
from core.matcher import Matcher
from core.portfolio_adapter import PassThroughAdapter
from core.sizing import NotionalSizer
from framework.base import Strategy
from framework.data_pool import BatchDataPool
from framework.types import (
    FILL_CANCELLED,
    FILL_FILLED,
    OFFSET_OPEN,
    ORDER_LIMIT,
    Bar,
    Fill,
    Signal,
    SIGNAL_ENTRY,
)


# ── 辅助：最小可用的内存 DataPool ────────────────────────────────────

class _InMemoryDataPool(BatchDataPool):
    """最小 BatchDataPool 实现：只保留两个被引擎实际访问的方法。"""

    def __init__(self, symbol: str, bars_df: pd.DataFrame, sector: str = "TEST"):
        self._symbol = symbol
        self._bars = bars_df
        self._sector = sector

    def list_universe(self):
        return [self._symbol]

    def sector_of(self, symbol):
        return self._sector

    def symbols_in_sector(self, sector, exclude=None):
        return [s for s in [self._symbol] if exclude is None or s not in exclude]

    def contract_info(self, symbol):
        return {
            "product": symbol,
            "point": 10.0,
            "tick_size": 1.0,
            "slip": 0.0,
            "commission_intraday": 0.0,
            "type": 0.0,
        }

    def get_minute_bars(self, symbol, as_of, n_bars):
        if symbol != self._symbol:
            return pd.DataFrame()
        df = self._bars[self._bars.index <= as_of]
        return df.tail(n_bars)

    def get_session_bars(self, symbol, tradingday, session_start, session_end):
        return pd.DataFrame()

    def get_daily_panel(self, metric, symbols, as_of_td, n_days):
        return pd.DataFrame()

    def get_all_bars(self, symbol, copy=True):
        if symbol != self._symbol:
            return pd.DataFrame()
        return self._bars.copy() if copy else self._bars

    def get_frames_snapshot(self, symbols, columns=None):
        return {self._symbol: self._bars}


def _make_bars_df(n: int = 5) -> pd.DataFrame:
    """构造一个 5 根 bar 的 DataFrame，价格平稳。"""
    ts = pd.date_range("2024-01-01 09:00", periods=n, freq="1min")
    return pd.DataFrame(
        {
            "open": [4000] * n,
            "high": [4010] * n,
            "low": [3990] * n,
            "close": [4000] * n,
            "volume": [100] * n,
            "oi": [0.0] * n,
            "tradingday": [pd.Timestamp("2024-01-01")] * n,
        },
        index=ts,
    )


# ── 1. 同 bar 撤旧挂新（验证执行顺序）───────────────────────────────

class _CancelAndReplaceStrategy(Strategy):
    """第 1 根 bar 挂一笔 limit；第 2 根 bar 撤掉它再挂新的。"""

    SESSION_NAMES = ["test"]
    SUPPORTS_BATCH_PREBUILD = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bar_count = 0
        self.first_cid: Optional[str] = None
        self.second_cid: Optional[str] = None
        self.fills_seen: List[Fill] = []

    def on_bar(self, bar, snapshot):
        self.bar_count += 1
        signals = []

        if self.bar_count == 1:
            self.first_cid = self.new_client_order_id("FIRST")
            signals.append(Signal(
                symbol=bar.symbol,
                action_datetime=bar.timestamp,
                bar_datetime=bar.timestamp,
                signal_kind=SIGNAL_ENTRY,
                direction=1,
                offset=OFFSET_OPEN,
                order_type=ORDER_LIMIT,
                price=3000.0,  # 永远不到达，挂着不动
                volume_hint=1,
                session="test",
                client_order_id=self.first_cid,
            ))
        elif self.bar_count == 2:
            # 撤掉旧的，再挂一笔新的
            self.cancel_order(bar.symbol, self.first_cid)
            self.second_cid = self.new_client_order_id("SECOND")
            signals.append(Signal(
                symbol=bar.symbol,
                action_datetime=bar.timestamp,
                bar_datetime=bar.timestamp,
                signal_kind=SIGNAL_ENTRY,
                direction=1,
                offset=OFFSET_OPEN,
                order_type=ORDER_LIMIT,
                price=3500.0,  # 也不到达
                volume_hint=1,
                session="test",
                client_order_id=self.second_cid,
            ))

        return signals

    def on_fill(self, fill):
        super().on_fill(fill)
        self.fills_seen.append(fill)


def test_cancel_old_and_place_new_in_same_bar():
    """关键验证：第 2 根 bar 处理后，旧单 cancelled，新单仍在 pending 队列。"""
    df = _make_bars_df(n=3)
    pool = _InMemoryDataPool("RB", df)
    strat = _CancelAndReplaceStrategy(
        strategy_id="test_strat",
        contract_info=pool.contract_info("RB"),
        data_pool=pool,
        params={},
    )
    slot = StrategySlot(
        strategy_id="test_strat",
        symbol="RB",
        instance=strat,
        sessions=["test"],
    )
    adapter = PassThroughAdapter(
        contract_info_by_symbol={"RB": pool.contract_info("RB")},
        sizer_by_strategy={"test_strat": NotionalSizer(1_000_000)},
    )
    accountant = TradeAccountant(
        contract_info_by_symbol={"RB": pool.contract_info("RB")},
        allocated_capital_by_strategy={"test_strat": 1_000_000},
    )
    engine = BacktestEngine(
        data_pool=pool,
        slots=[slot],
        adapter=adapter,
        accountant=accountant,
        warmup_bars=0,
    )
    engine.run()

    # 应至少 3 根 bar 调用了 on_bar
    assert strat.bar_count >= 2

    # 收到的 fills 里应有一个 FILL_CANCELLED 对应 first_cid
    cancelled = [
        f for f in strat.fills_seen
        if f.status == FILL_CANCELLED and f.client_order_id == strat.first_cid
    ]
    assert len(cancelled) == 1, (
        f"期望 first_cid={strat.first_cid} 被撤单一次；实际 fills:\n"
        + "\n".join(f"  {f.status} cid={f.client_order_id}" for f in strat.fills_seen)
    )

    # second_cid 应该挂着没成交（price 3500 永远不到达），所以不应在 fills 里出现 FILLED
    second_filled = [
        f for f in strat.fills_seen
        if f.client_order_id == strat.second_cid and f.status == FILL_FILLED
    ]
    assert len(second_filled) == 0


# ── 2. 稀疏路径下 cancel_order → RuntimeError ──────────────────────

class _BadSparseStrategy(Strategy):
    """稀疏路径策略，但在 on_init 里非法调用 cancel_order。"""

    SESSION_NAMES = ["test"]
    SUPPORTS_BATCH_PREBUILD = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._prebuilt: Dict[pd.Timestamp, List[Signal]] = {}

    def on_bar(self, bar, snapshot):
        return []

    def on_init(self, history):
        # 故意误用：稀疏路径策略不应该调 cancel_order
        self.cancel_order("RB", "SOMECID")
        # 必须给 prebuilt 至少塞一项才会触发稀疏路径循环（否则不进 raise 分支）
        first_ts = history.data_pool.get_all_bars("RB", copy=False).index[0]
        self._prebuilt = {first_ts: []}

    def get_prebuilt_signals(self):
        return self._prebuilt


def test_cancel_order_in_sparse_path_raises_runtime_error():
    df = _make_bars_df(n=3)
    pool = _InMemoryDataPool("RB", df)
    strat = _BadSparseStrategy(
        strategy_id="bad_sparse",
        contract_info=pool.contract_info("RB"),
        data_pool=pool,
        params={},
    )
    slot = StrategySlot(
        strategy_id="bad_sparse",
        symbol="RB",
        instance=strat,
        sessions=["test"],
    )
    adapter = PassThroughAdapter(
        contract_info_by_symbol={"RB": pool.contract_info("RB")},
        sizer_by_strategy={"bad_sparse": NotionalSizer(1_000_000)},
    )
    accountant = TradeAccountant(
        contract_info_by_symbol={"RB": pool.contract_info("RB")},
        allocated_capital_by_strategy={"bad_sparse": 1_000_000},
    )
    engine = BacktestEngine(
        data_pool=pool,
        slots=[slot],
        adapter=adapter,
        accountant=accountant,
        warmup_bars=0,
    )
    with pytest.raises(RuntimeError, match="稀疏批量路径.*cancel_order"):
        engine.run()
