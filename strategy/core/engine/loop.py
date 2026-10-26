"""
core/engine/loop.py  ——  BacktestEngine 主类（时间游标 / 多策略调度）

负责:
    - 多品种数据通过 DataPool 访问
    - 时间游标同步推进（按所有 universe 品种的 timestamp 并集）
    - 每根 bar：调度 strategy.on_bar → adapter.process → matcher.match
    - 上一根 bar 提交的 orders 在本根 bar 撮合，回灌 Fill 给 strategy + accountant
    - 日终钩子（on_day_end）
    - 汇总输出 trades_df / nav_df / portfolio_nav_df

调度模式：
    - 单策略 = 1 个 strategy + PassThrough adapter
    - 团队独立 = N 个 strategy + PassThrough adapter
    - 团队组合 = N 个 strategy + Capped/Dedup adapter
"""
from __future__ import annotations

import time
import traceback
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd
from tqdm import tqdm

from framework.base import Strategy
from framework.action_recorder import ActionRecorder
from framework.signal_recorder import SignalRecorder
from framework.snapshot import HistoryView, Snapshot
from framework.types import Bar, Signal

from ..accounting import TradeAccountant
from ..data_pool import BacktestDataPool
from ..matcher import Matcher
from ..portfolio_adapter import BasePortfolioAdapter, PassThroughAdapter
from .pre_build import run_parallel_prebuild
from .signal_pipeline import handle_fill, tag_signal


@dataclass
class StrategySlot:
    """一个策略实例的运行槽位（每个 strategy × 每个 symbol 一个）。"""
    strategy_id: str
    symbol: str
    instance: Strategy
    sessions: List[str]


@dataclass
class EngineResult:
    trades_df: pd.DataFrame
    nav_df: pd.DataFrame
    portfolio_nav_df: pd.DataFrame
    elapsed_sec: float
    n_strategies: int
    n_symbols: int
    errors: List[str]


class BacktestEngine:
    """
    回测引擎。

    构造:
        engine = BacktestEngine(
            data_pool        = BacktestDataPool(...),
            slots            = [StrategySlot(...), ...],
            adapter          = PassThroughAdapter(...) | CappedCapitalAdapter(...) | ...,
            accountant       = TradeAccountant(...),
            warmup_bars      = 500,
            start            = pd.Timestamp("2022-01-01"),
            end              = pd.Timestamp("2026-05-16"),
            limit_max_wait   = 20,
        )
        result = engine.run()
    """

    def __init__(
        self,
        data_pool: BacktestDataPool,
        slots: List[StrategySlot],
        adapter: BasePortfolioAdapter,
        accountant: TradeAccountant,
        warmup_bars: int = 500,
        start: Optional[pd.Timestamp] = None,
        end: Optional[pd.Timestamp] = None,
        limit_max_wait: int = 20,
        signal_recorder: Optional[SignalRecorder] = None,
        action_recorder: Optional[ActionRecorder] = None,
    ) -> None:
        self.data_pool   = data_pool
        self.slots       = slots
        self.adapter     = adapter
        self.accountant  = accountant
        self.warmup_bars = int(warmup_bars)
        self.start       = start
        self.end         = end
        self.signal_recorder = signal_recorder
        self.action_recorder = action_recorder
        self.matcher     = Matcher(
            contract_info_by_symbol = {s.symbol: data_pool.contract_info(s.symbol) for s in slots},
            limit_max_wait_bars     = limit_max_wait,
        )

        self._last_bar_by_symbol: Dict[str, Bar] = {}

    # ──────────────────────────────────────────────────────────────────
    # 主循环
    # ──────────────────────────────────────────────────────────────────

    def run(self) -> EngineResult:
        t0 = time.time()
        errors: List[str] = []

        self._warmup_all_slots()

        # 路由规则：
        #   A) 单品种                          → 单品种快路径（直接按行迭代）
        #   B) 多品种 + 每品种唯一 slot
        #      + PassThrough adapter           → 逐品种顺序跑快路径（等价且最快）
        #   C) 其余（组合 adapter / 多策略共享品种）→ 全 universe 时间游标慢路径
        slot_symbols = {s.symbol for s in self.slots}
        all_unique = len(self.slots) == len(slot_symbols)
        use_fast_sequential = (
            len(slot_symbols) > 1
            and all_unique
            and isinstance(self.adapter, PassThroughAdapter)
        )

        # 批量信号稀疏路径：策略在 on_init 里预算了全部信号（通过
        # ``get_prebuilt_signals()`` 暴露），只需在信号时刻 + 成交时刻做撮合，
        # 跳过全量 bar 迭代。引擎只查显式契约，不耦合策略类的私有属性。
        all_batch = all(
            s.instance.get_prebuilt_signals() is not None
            for s in self.slots
        )

        if all_batch and len(slot_symbols) == 1:
            timeline, loop_elapsed = self._run_single_symbol_sparse(
                list(slot_symbols)[0], errors, slots=self.slots
            )
        elif all_batch and use_fast_sequential:
            timeline, loop_elapsed = self._run_each_symbol(errors, sparse=True)
        elif len(slot_symbols) == 1:
            timeline, loop_elapsed = self._run_single_symbol(
                list(slot_symbols)[0], errors, slots=self.slots
            )
        elif use_fast_sequential:
            timeline, loop_elapsed = self._run_each_symbol(errors, sparse=False)
        else:
            timeline, loop_elapsed = self._run_multi_symbol(errors)

        if not timeline:
            return EngineResult(
                trades_df        = pd.DataFrame(),
                nav_df           = pd.DataFrame(),
                portfolio_nav_df = pd.DataFrame(),
                elapsed_sec      = time.time() - t0,
                n_strategies     = len({s.strategy_id for s in self.slots}),
                n_symbols        = len(slot_symbols),
                errors           = errors or ["empty timeline"],
            )

        elapsed = time.time() - t0

        trades_df = self.accountant.trades_dataframe()
        session_names_by_strategy = {s.strategy_id: s.sessions or ["ALL"] for s in self.slots}
        symbols_by_strategy: Dict[str, List[str]] = {}
        for s in self.slots:
            symbols_by_strategy.setdefault(s.strategy_id, []).append(s.symbol)
        symbols_by_strategy = {k: sorted(set(v)) for k, v in symbols_by_strategy.items()}

        trading_days_by_symbol = self._trading_days_by_symbol()
        nav_df = self.accountant.nav_dataframe(
            session_names_by_strategy,
            trading_days_by_symbol,
            symbols_by_strategy,
        )
        portfolio_nav_df = self._portfolio_nav(nav_df)

        return EngineResult(
            trades_df        = trades_df,
            nav_df           = nav_df,
            portfolio_nav_df = portfolio_nav_df,
            elapsed_sec      = elapsed,
            n_strategies     = len({s.strategy_id for s in self.slots}),
            n_symbols        = len(slot_symbols),
            errors           = errors,
        )

    # ── 主步进逻辑：单 bar 的"撮合 → 决策 → 下单 → 立即撮合"四阶段 ──────

    def _step_bar(
        self,
        ts: pd.Timestamp,
        bar_by_symbol: Dict[str, Bar],
        slots_by_symbol: Dict[str, List[StrategySlot]],
        universe: List[str],
        sector_of: Callable[[str], str],
        errors: List[str],
    ) -> None:
        """
        在时间游标 ``ts`` 上对所有可见品种推进一个 bar（五阶段）:
            1. 撮合上一根 bar 提交的 pending 订单
            2. 调每个 slot.on_bar 收集 signals（策略可调用 cancel_order 累积撤单）
            3. drain_cancels：处理本 bar 内策略发起的撤单请求 → FILL_CANCELLED
            4. adapter.process → orders（client_order_id 透传）
            5. submit_pending → 立即撮合（ORDER_EXACT 立即成交；重复 cid raise）

        被 ``_run_single_symbol`` / ``_run_multi_symbol`` 共用，避免维护 2 套
        几乎一致的循环体。``bar_by_symbol`` 单品种路径只含 1 项。

        关键顺序保证:
            - 撤单在新挂单之前：同 bar "撤旧挂新" 语义清晰
            - on_fill(FILL_CANCELLED) 在新单挂出之前触发：策略可在 on_fill 里
              更新 pending 状态，但不影响本 bar 已决策好的新挂单
        """
        # 1. 撮合上一根 bar 提交的 pending 订单
        for sym, bar in bar_by_symbol.items():
            slots_here = slots_by_symbol.get(sym, [])
            for fill in self.matcher.match_at(bar):
                if self.action_recorder is not None:
                    self.action_recorder.record_fill(
                        fill, ts, pending_after=self.matcher.pending_count(fill.symbol),
                    )
                # 组合层 adapter 状态先于 strategy.on_fill 更新，保证后续 process 能
                # 看到最新的 open_positions（CappedPositionAdapter 等需要）。
                self.adapter.on_fill(fill)
                handle_fill(fill, slots_here, self.accountant)
            self._last_bar_by_symbol[sym] = bar

        # 2. 调每个 slot.on_bar 收集 signals
        signals_by_strategy: Dict[str, List[Signal]] = {}
        slots_with_cancels: List[StrategySlot] = []
        for sym, bar in bar_by_symbol.items():
            for slot in slots_by_symbol.get(sym, []):
                try:
                    snapshot = Snapshot(
                        current_symbol = sym,
                        current_bar    = bar,
                        ts             = ts,
                        universe       = universe,
                        sector         = sector_of(sym),
                        data_pool      = self.data_pool,
                    )
                    for sig in slot.instance.on_bar(bar, snapshot) or []:
                        tag_signal(sig, slot.strategy_id)
                        if self.signal_recorder is not None:
                            self.signal_recorder.record(sig, bar)
                        signals_by_strategy.setdefault(slot.strategy_id, []).append(sig)
                    # 策略可能在 on_bar 里调过 cancel_order，记下待 drain
                    if slot.instance._pending_cancels:
                        slots_with_cancels.append(slot)
                except Exception as e:
                    errors.append(f"{slot.strategy_id}/{sym}@{ts}: {e}")
                    tqdm.write(f"  [ERROR] {slot.strategy_id}/{sym}@{ts}: {e}")
                    traceback.print_exc()

        # 3. drain_cancels：处理 on_bar 内累积的撤单请求
        for slot in slots_with_cancels:
            for cancel_sym, cid in slot.instance._drain_cancels():
                if self.action_recorder is not None:
                    self.action_recorder.record_cancel_request(
                        strategy_id     = slot.strategy_id,
                        symbol          = cancel_sym,
                        ts              = ts,
                        client_order_id = cid,
                        pending_before  = self.matcher.pending_count(cancel_sym),
                    )
                fill = self.matcher.cancel(cancel_sym, cid)
                if fill is not None:
                    if self.action_recorder is not None:
                        self.action_recorder.record_fill(
                            fill, ts, pending_after=self.matcher.pending_count(fill.symbol),
                        )
                    self.adapter.on_fill(fill)
                    handle_fill(
                        fill,
                        slots_by_symbol.get(cancel_sym, []),
                        self.accountant,
                    )

        # 4-5. adapter.process → orders → submit_pending → 立即撮合
        if not signals_by_strategy:
            return
        ref_price = {s: b.close for s, b in bar_by_symbol.items()}
        orders = self.adapter.process(ts, signals_by_strategy, ref_price)

        # 4.5 adapter 在 process 期间累积的 cap-drop fills 立即回灌给策略，
        # 让带 _in_flight 类去重 gate 的策略能在 stream/batch 两路径下保持
        # 字节一致的本地状态轨迹（FILL_REJECTED → strategy.on_fill → reset gate）。
        for drop_fill in self.adapter.take_pending_drop_fills():
            if self.action_recorder is not None:
                self.action_recorder.record_fill(
                    drop_fill, ts, pending_after=self.matcher.pending_count(drop_fill.symbol),
                )
            handle_fill(
                drop_fill, slots_by_symbol.get(drop_fill.symbol, []), self.accountant,
            )

        if not orders:
            return
        if self.action_recorder is not None:
            for o in orders:
                self.action_recorder.record_place(
                    o, ts, pending_after=self.matcher.pending_count(o.symbol),
                )
        for fill in self.matcher.submit_pending(orders, ts):
            if self.action_recorder is not None:
                self.action_recorder.record_fill(
                    fill, ts, pending_after=self.matcher.pending_count(fill.symbol),
                )
            self.adapter.on_fill(fill)
            handle_fill(fill, slots_by_symbol.get(fill.symbol, []), self.accountant)

    # ── 快速路径：单品种 ─────────────────────────────────────────────────

    def _run_single_symbol(
        self,
        symbol: str,
        errors: List[str],
        slots: Optional[List[StrategySlot]] = None,
        show_bar: bool = True,
    ) -> Tuple[List[pd.Timestamp], float]:
        """直接按品种 DataFrame 行迭代，跳过全 universe 时间游标扫描。"""
        df = self.data_pool.get_all_bars(symbol, copy=False)
        if df is None or df.empty:
            return [], 0.0
        if self.start is not None:
            df = df[df.index >= self.start]
        if self.end is not None:
            df = df[df.index <= self.end]
        if df.empty:
            return [], 0.0

        universe = self.data_pool.list_universe()
        sector   = self.data_pool.sector_of(symbol)
        if slots is None:
            slots = self.slots
        slots_by_symbol = {symbol: slots}

        timeline: List[pd.Timestamp] = []
        t0 = time.time()

        it = df.itertuples()
        if show_bar:
            it = tqdm(it, total=len(df), desc=f"回测推进 {symbol}", ncols=80, leave=False)
        for row in it:
            ts  = pd.Timestamp(row.Index)
            bar = Bar(
                symbol     = symbol,
                timestamp  = ts,
                tradingday = row.tradingday,
                open       = float(row.open),
                high       = float(row.high),
                low        = float(row.low),
                close      = float(row.close),
                volume     = float(row.volume),
                oi         = float(getattr(row, "oi", 0.0)),
                is_daily_close = bool(getattr(row, "is_daily_close", False)),
            )
            timeline.append(ts)
            self._step_bar(
                ts              = ts,
                bar_by_symbol   = {symbol: bar},
                slots_by_symbol = slots_by_symbol,
                universe        = universe,
                sector_of       = lambda _s: sector,
                errors          = errors,
            )

        return timeline, time.time() - t0

    # ── 稀疏路径：批量信号，只访问信号 + 成交时刻 ───────────────────────

    def _run_single_symbol_sparse(
        self,
        symbol: str,
        errors: List[str],
        slots: Optional[List[StrategySlot]] = None,
        show_bar: bool = True,
    ) -> Tuple[List[pd.Timestamp], float]:
        """
        批量信号稀疏路径（单品种）。

        策略在 on_init 里已预算好信号字典（通过 ``get_prebuilt_signals()``
        暴露，``{timestamp: [Signal]}``）。本方法只访问信号时刻 + 成交
        时刻，跳过全部无动作 bar。复杂度：O(N_trades)  vs  O(N_bars)。
        """
        df = self.data_pool.get_all_bars(symbol, copy=False)
        if df is None or df.empty:
            return [], 0.0
        if self.start is not None:
            df = df[df.index >= self.start]
        if self.end is not None:
            df = df[df.index <= self.end]
        if df.empty:
            return [], 0.0

        if slots is None:
            slots = self.slots

        ts_index = df.index
        all_ts: set = set()
        t0 = time.time()

        for slot in slots:
            batch_signals: dict = slot.instance.get_prebuilt_signals() or {}

            for sig_ts in sorted(batch_signals.keys()):
                # 稀疏路径不调 on_bar，策略不应调用 cancel_order。
                # 若 _pending_cancels 非空，说明策略在 on_init / on_day_end /
                # 其它钩子里误调，立即抛错提示走标准路径。
                if slot.instance._pending_cancels:
                    raise RuntimeError(
                        f"策略 {slot.strategy_id} 走了稀疏批量路径，但调用了 cancel_order；"
                        f"请设置 SUPPORTS_BATCH_PREBUILD = False，让回测走标准 on_bar "
                        f"路径以保持与实盘一致。"
                    )

                if self.start is not None and sig_ts < self.start:
                    continue
                if self.end is not None and sig_ts > self.end:
                    continue
                if sig_ts not in df.index:
                    continue

                sigs = batch_signals[sig_ts]
                if not sigs:
                    continue

                # 构造 signal 触发时的 Bar 上下文（供 signal_recorder 落盘对账用）
                trigger_bar: Optional[Bar] = None
                if self.signal_recorder is not None:
                    row_at = df.loc[sig_ts]
                    trigger_bar = Bar(
                        symbol     = symbol,
                        timestamp  = sig_ts,
                        tradingday = row_at["tradingday"],
                        open       = float(row_at["open"]),
                        high       = float(row_at["high"]),
                        low        = float(row_at["low"]),
                        close      = float(row_at["close"]),
                        volume     = float(row_at["volume"]),
                        oi         = float(row_at.get("oi", 0.0)),
                    )

                for sig in sigs:
                    tag_signal(sig, slot.strategy_id)
                    if self.signal_recorder is not None:
                        self.signal_recorder.record(sig, trigger_bar)

                ref_close = float(df.at[sig_ts, "close"])
                orders = self.adapter.process(
                    ts                  = sig_ts,
                    signals_by_strategy = {slot.strategy_id: sigs},
                    ref_price_by_symbol = {symbol: ref_close},
                )

                # adapter cap-drop fills 立即回灌（同 _step_bar 阶段 4.5；这里只
                # 有单 slot 单 symbol，所以仅回灌给该 slot）。
                for drop_fill in self.adapter.take_pending_drop_fills():
                    if self.action_recorder is not None:
                        self.action_recorder.record_fill(
                            drop_fill, sig_ts,
                            pending_after=self.matcher.pending_count(drop_fill.symbol),
                        )
                    handle_fill(drop_fill, [slot], self.accountant)

                if not orders:
                    continue

                # ORDER_EXACT 立即成交（submit_pending 内部处理）
                if self.action_recorder is not None:
                    for o in orders:
                        self.action_recorder.record_place(
                            o, sig_ts, pending_after=self.matcher.pending_count(o.symbol),
                        )
                immediate = self.matcher.submit_pending(orders, sig_ts)
                for fill in immediate:
                    if self.action_recorder is not None:
                        self.action_recorder.record_fill(
                            fill, sig_ts, pending_after=self.matcher.pending_count(fill.symbol),
                        )
                    self.adapter.on_fill(fill)
                    handle_fill(fill, [slot], self.accountant)
                    all_ts.add(sig_ts)

                # 找下一根 bar，用于 ORDER_MARKET 成交
                pos = ts_index.searchsorted(sig_ts, side="right")
                if pos >= len(ts_index):
                    continue

                next_ts  = ts_index[pos]
                next_row = df.iloc[pos]
                fill_bar = Bar(
                    symbol     = symbol,
                    timestamp  = next_ts,
                    tradingday = next_row["tradingday"],
                    open       = float(next_row["open"]),
                    high       = float(next_row["high"]),
                    low        = float(next_row["low"]),
                    close      = float(next_row["close"]),
                    volume     = float(next_row["volume"]),
                    oi         = float(next_row.get("oi", 0.0)),
                )
                fills = self.matcher.match_at(fill_bar)
                for fill in fills:
                    if self.action_recorder is not None:
                        self.action_recorder.record_fill(
                            fill, next_ts, pending_after=self.matcher.pending_count(fill.symbol),
                        )
                    self.adapter.on_fill(fill)
                    handle_fill(fill, [slot], self.accountant)
                    all_ts.add(sig_ts)
                    all_ts.add(next_ts)

        return sorted(all_ts), time.time() - t0

    # ── 逐品种顺序路径（PassThrough 独立策略，sparse=批量快路径） ──────

    def _run_each_symbol(
        self, errors: List[str], sparse: bool,
    ) -> Tuple[List[pd.Timestamp], float]:
        """
        每个 symbol 独立运行，顺序调用单品种路径；总复杂度 O(Σ bars_per_symbol)，
        避免全 universe 时间游标扫描。

        ``sparse=True``  → 调单品种稀疏路径（要求各 slot 已预算好批量信号）
        ``sparse=False`` → 调单品种快路径（按 DataFrame 行迭代）
        """
        slots_by_symbol: Dict[str, List[StrategySlot]] = {}
        for slot in self.slots:
            slots_by_symbol.setdefault(slot.symbol, []).append(slot)

        inner = (
            self._run_single_symbol_sparse if sparse else self._run_single_symbol
        )
        desc = "品种进度 (batch)" if sparse else "品种进度"

        all_ts: set = set()
        t0 = time.time()
        for symbol in tqdm(list(slots_by_symbol.keys()), desc=desc, ncols=80):
            tl, _ = inner(
                symbol, errors, slots=slots_by_symbol[symbol], show_bar=False
            )
            all_ts.update(tl)
        return sorted(all_ts), time.time() - t0

    # ── 通用路径：多品种 ─────────────────────────────────────────────────

    def _run_multi_symbol(
        self, errors: List[str]
    ) -> Tuple[List[pd.Timestamp], float]:
        """多品种时按全 universe ts 并集扫描。"""
        timeline = self._build_timeline()
        if not timeline:
            return [], 0.0

        slots_by_symbol: Dict[str, List[StrategySlot]] = {}
        for slot in self.slots:
            slots_by_symbol.setdefault(slot.symbol, []).append(slot)
        universe = self.data_pool.list_universe()
        sector_of = self.data_pool.sector_of

        t0 = time.time()
        for ts in tqdm(timeline, desc="回测推进", ncols=80):
            ts = pd.Timestamp(ts)

            ts_bars: Dict[str, Bar] = {}
            for sym in universe:
                bars_df = self.data_pool.get_minute_bars(sym, ts, n_bars=1)
                if bars_df.empty:
                    continue
                row = bars_df.iloc[-1]
                if row.name != ts:
                    continue
                ts_bars[sym] = Bar(
                    symbol     = sym,
                    timestamp  = row.name,
                    tradingday = row["tradingday"],
                    open       = float(row["open"]),
                    high       = float(row["high"]),
                    low        = float(row["low"]),
                    close      = float(row["close"]),
                    volume     = float(row["volume"]),
                    oi         = float(row.get("oi", 0.0)),
                    is_daily_close = bool(row.get("is_daily_close", False)),
                )

            self._step_bar(
                ts              = ts,
                bar_by_symbol   = ts_bars,
                slots_by_symbol = slots_by_symbol,
                universe        = universe,
                sector_of       = sector_of,
                errors          = errors,
            )

        return timeline, time.time() - t0

    # ──────────────────────────────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────────────────────────────

    def _build_timeline(self) -> List[pd.Timestamp]:
        """所有 universe 品种的 timestamp 并集，按时间排序；裁剪到 [start, end]。"""
        all_ts: set = set()
        for sym in self.data_pool.list_universe():
            df = self.data_pool.get_all_bars(sym, copy=False)
            if df is None or df.empty:
                continue
            all_ts.update(df.index)
        timeline = sorted(all_ts)
        if self.start is not None:
            timeline = [t for t in timeline if t >= self.start]
        if self.end is not None:
            timeline = [t for t in timeline if t <= self.end]
        return timeline

    def _trading_days_by_symbol(self) -> Dict[str, List[pd.Timestamp]]:
        """每个 symbol 实际有 bar 的 trading days（裁剪到 [start, end]）。

        NAV 只写 symbol 实际存在的交易日，避免给未上市/已退市 symbol
        补 daily_pnl=0 行后被下游组合层 ``mean()`` 稀释当日收益率。
        """
        result: Dict[str, List[pd.Timestamp]] = {}
        for sym in self.data_pool.list_universe():
            df = self.data_pool.get_all_bars(sym, copy=False)
            if df is None or df.empty:
                result[sym] = []
                continue
            if self.start is not None:
                df = df[df.index >= self.start]
            if self.end is not None:
                df = df[df.index <= self.end]
            if df.empty:
                result[sym] = []
                continue
            days = sorted(
                pd.Timestamp(d) for d in df["tradingday"].dt.normalize().unique()
            )
            result[sym] = days
        return result

    def _warmup_all_slots(self) -> None:
        """对每个 slot 调用 on_init，传入 [开始之前 N 根 bar] 作为预热段。

        当 ≥2 个 slot 同时支持 batch_prebuild_args + run_batch_prebuild 时，
        交给 ``pre_build.run_parallel_prebuild`` 在 spawn 子进程并行预算并
        ``set_prebuilt_signals(...)`` 回灌；主进程后续 on_init 只做一次
        轻量收尾。
        """
        run_parallel_prebuild(self.slots)

        iterator = (
            tqdm(self.slots, desc="预热策略", ncols=80)
            if len(self.slots) > 1
            else self.slots
        )
        for slot in iterator:
            if self.start is not None:
                df = self.data_pool.get_minute_bars(slot.symbol, self.start, n_bars=self.warmup_bars)
            else:
                df = self.data_pool.get_all_bars(slot.symbol, copy=False)
                if df is not None and not df.empty:
                    df = df.head(self.warmup_bars)
            view = HistoryView(
                symbol    = slot.symbol,
                own_bars  = df if df is not None else pd.DataFrame(),
                data_pool = self.data_pool,
            )
            try:
                slot.instance.on_init(view)
            except Exception as e:
                tqdm.write(f"  [WARN] {slot.strategy_id}/{slot.symbol} on_init 失败: {e}")
                traceback.print_exc()

    def _portfolio_nav(self, nav_df: pd.DataFrame) -> pd.DataFrame:
        """组合 NAV（V0.3 口径：每品种共享 per_slot_capital 资金池）。

        计算链路（与 ``2026_04_17_CTA_V0.3 / run_portfolio._build_symbol_nav +
        performance.build_portfolio_daily`` 等价）：

            1. 先按 ``(date, symbol)`` 聚合：把同品种当日多策略/多 session 的
               ``daily_pnl`` / ``commission`` / ``num_trades`` 全部 sum。
            2. ``daily_pnl_pct(symbol) = sum(daily_pnl) / per_slot_capital``
               其中 ``per_slot_capital`` = ``per_strategy_capital``（默认 100 万）。
               业务语义：**单品种 100 万资金池**，多策略共享，max_stack 控制
               并发持仓上限（可达 max_stack 倍杠杆，符合期货保证金交易实践）。
            3. 组合 ``daily_pnl_pct = mean(daily_pnl_pct(symbol)) over symbols``
               ≡ ``sum(daily_pnl) / (n_symbols × per_slot_capital)``。
            4. ``net_value = cumprod(1 + daily_pnl_pct)``。

        旧实现直接对 ``(date × symbol × strategy × session)`` 全部行 mean，
        相当于把多策略/多 session 当独立资金 slot，分母被稀释 K 倍（K =
        平均每品种的 strategy×session 组合数），导致 NAV 严重低估。
        """
        if nav_df.empty:
            return nav_df
        # per-slot 基数：多 strategy cap 一致时（默认 100 万）就是单基数
        per_slot = max(self.accountant._cap.values()) if self.accountant._cap else 1_000_000

        by_sym = (
            nav_df.groupby(["date", "symbol"], sort=True)
            .agg(
                daily_pnl  = ("daily_pnl",  "sum"),
                commission = ("commission", "sum"),
                num_trades = ("num_trades", "sum"),
                win_trades = ("win_trades", "sum"),
            )
            .reset_index()
        )
        by_sym["daily_pnl_pct"] = by_sym["daily_pnl"] / per_slot

        port = (
            by_sym.groupby("date", sort=True)
            .agg(
                daily_pnl     = ("daily_pnl",     "sum"),
                commission    = ("commission",    "sum"),
                num_trades    = ("num_trades",    "sum"),
                win_trades    = ("win_trades",    "sum"),
                num_symbols   = ("symbol",        "nunique"),
                daily_pnl_pct = ("daily_pnl_pct", "mean"),
            )
            .reset_index()
        )
        port["symbol"]    = "PORTFOLIO"
        port["strategy"]  = "ALL"
        port["session"]   = "ALL"
        port["daily_pnl_pct"] = port["daily_pnl_pct"].round(8)
        port["net_value"]     = (1 + port["daily_pnl_pct"]).cumprod().round(4)
        return port[[
            "date", "symbol", "strategy", "session", "num_symbols",
            "daily_pnl", "daily_pnl_pct", "commission",
            "num_trades", "win_trades", "net_value",
        ]]
