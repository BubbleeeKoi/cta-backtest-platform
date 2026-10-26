"""
jerome/strategy.py  ——  策略入口与框架对接

回测与实盘共用本文件；差异仅在 ``data_pool`` / ``matcher`` / 行情来源。

模块划分:
    strategy.py    框架对接 + on_bar/on_fill 调度（本文件）
    decision.py    入场 / 平仓决策（纯函数；EntryPlan / ExitPlan）
    features.py    滚动指标累加器（IndicatorWindow）
    filters.py     入场 / 平仓闸门（check_xxx 纯函数）
    params.py      StrategyParams / CarryState / SESSION_NAME / STRATEGY_NAME

策略逻辑:
  - **入场**：``[observe_start, entry_cutoff)`` 内按 ``mid ± k·ATR_short`` 多空
    各挂 ``n_legs`` 层限价单；``vol_ratio < vol_shrink_ratio`` 时撤所有未成交
    入场单；任一层成交 → 撤其它所有层。
  - **平仓**：成交后挂 ``entry_price ± tp_atr·ATR`` 限价止盈；每
    ``tp_adjust_every_bars`` 根 bar 若浮亏达阈值则撤旧挂新（最多
    ``tp_adjust_max_times`` 次）。
  - **止损**：持仓 ≥ ``sl_max_hold_bars`` 或浮亏 ≥ ``sl_atr·ATR`` → 撤平仓
    单 + 市价止损。
  - **强平**：``close_time`` 撤所有未成交挂单 + 持仓市价强平。
"""
from __future__ import annotations

from typing import List, Optional

from framework import (
    Bar,
    Fill,
    Signal,
    Strategy as BaseStrategy,
    FILL_CANCELLED,
    FILL_EXPIRED,
    FILL_FILLED,
    OFFSET_CLOSE,
    OFFSET_OPEN,
    ORDER_LIMIT,
    ORDER_MARKET,
    SIGNAL_ENTRY,
    SIGNAL_FORCE_CLOSE,
    SIGNAL_STOP_LOSS,
    SIGNAL_TAKE_PROFIT,
)
from framework.snapshot import HistoryView, Snapshot

from .decision import (
    EntryPlan,
    ExitPlan,
    plan_entry_legs,
    plan_exit_decision,
)
from .features import IndicatorWindow
from .filters import check_can_remit_legs, check_keep_pending_legs
from .params import (
    NAV_SESSION_NAMES,
    SESSION_NAME,
    STRATEGY_NAME,
    CarryState,
    StrategyParams,
)


# 终态：on_fill 收到这些 status 后即可清理本地业务字典。
_TERMINAL_FILL_STATUSES = (FILL_FILLED, FILL_CANCELLED, FILL_EXPIRED, "rejected")


class Strategy(BaseStrategy):
    """挂单生命周期演示策略：多层入场 + 撤单 + 动态止盈 + 市价止损。"""

    REQUIRED_UNIVERSE = "self"

    SESSION_NAMES: List[str] = list(NAV_SESSION_NAMES)

    # 必须为 False：用了 cancel_order 的策略不能走稀疏批量预算路径。
    SUPPORTS_BATCH_PREBUILD = False

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        # __init__ 分三段构造，便于下游 on_init / on_bar 直接复用同一组 self.*：
        #   1) 配置 / 路径选择常量    —— 受 params 决定，一经构造不再变
        #   2) 跨日 / 跨品种长期状态  —— 滚动指标窗口
        #   3) 单日 intraday 状态     —— CarryState（每日 reset）
        self._init_config()
        self._init_persistent_state()
        self._init_intraday_state()

    # ── 子状态初始化（仅由 __init__ 调用；保持顺序） ────────────────────

    def _init_config(self) -> None:
        """params / 资金（受 params 决定，一经构造不再变）。"""
        self._params: StrategyParams = StrategyParams.from_dict(self.params)
        self._allocated_capital: float = float(
            self.params.get("allocated_capital", 1_000_000)
        )
        # 仅由 ``_enable_test_mode()`` 在验证工具内开启；生产环境永不触发。
        self._signal_log: Optional[List[dict]] = None

    def _init_persistent_state(self) -> None:
        """跨日 / 跨品种长期状态：滚动指标窗口（ATR / mid 队列跨日累积）。"""
        self._indicators = IndicatorWindow(self._params)

    def _init_intraday_state(self) -> None:
        """单日 intraday 状态：CarryState（每天 reset）。"""
        self._state = CarryState()

    # ── 验证工具专用 hook（生产路径不调用） ─────────────────────────────

    def _enable_test_mode(self) -> None:
        """打开 ``_signal_log`` 录制；只供 verify 工具用。"""
        self._signal_log = []

    # ── on_init / on_bar / on_fill ─────────────────────────────────────

    def on_init(self, history: HistoryView) -> None:
        """用预热段 ``HistoryView.own_bars`` 灌入滚动指标，确保第一根真实
        bar 到来时 ATR 已就绪。
        """
        own = getattr(history, "own_bars", None)
        if own is None or own.empty:
            return
        for row in own.itertuples():
            self._indicators.update(_BarLike(row.close, row.high, row.low))

    def on_bar(self, bar: Bar, snapshot: Snapshot) -> List[Signal]:
        sigs = self._on_bar_inner(bar, snapshot)
        if self._signal_log is not None:
            for s in sigs:
                self._signal_log.append({
                    "bar_datetime":    s.bar_datetime,
                    "action_datetime": s.action_datetime,
                    "signal_kind":     s.signal_kind,
                    "direction":       int(s.direction),
                    "offset":          s.offset,
                    "tag":             s.tag or "",
                })
        return sigs

    def _on_bar_inner(self, bar: Bar, snapshot: Snapshot) -> List[Signal]:
        state = self._state

        # 跨日重置（在更新指标之前判定；午盘不归零，避免误伤指标）
        if state.current_td is None or bar.tradingday != state.current_td:
            state.reset_for_new_day(bar.tradingday)

        # 更新滚动指标
        self._indicators.update(bar)
        state.bar_idx += 1

        # close_time 之后：撤所有挂单 + 持仓发市价强平
        if bar.timestamp.time() >= self._params.close_time:
            return self._dispatch_force_close(bar)

        # 早于 observe_start：仅累计指标，不做任何动作
        if bar.timestamp.time() < self._params.observe_start:
            return []

        # 持仓非空：管理平仓限价单 / 市价止损
        if not self.position.is_flat and state.position_direction != 0:
            return self._dispatch_exit(bar)

        # 空仓：管理入场挂单
        return self._dispatch_entries(bar)

    def on_fill(self, fill: Fill) -> None:
        """成交回报处理。

        必须先调 ``super().on_fill(fill)`` 让 framework 自动维护 ``self.position``，
        然后再更新本策略业务字典。
        """
        super().on_fill(fill)

        cid = fill.client_order_id
        state = self._state

        # 入场单成交：进入持仓态 + 撤其它所有层
        if cid in state.entry_pending and fill.status == FILL_FILLED:
            direction = int(state.entry_pending[cid]["direction"])
            state.position_direction = direction
            state.entry_price = float(
                fill.fill_price or state.entry_pending[cid]["price"]
            )
            state.entry_bar_idx = state.bar_idx
            state.last_tp_adjust_bar = state.bar_idx
            state.tp_adjust_times = 0
            others = [c for c in state.entry_pending if c != cid]
            for other_cid in others:
                self.cancel_order(self.symbol, other_cid)
            state.entry_pending.pop(cid, None)
            return

        # 入场单终态（撤单 / 过期 / 拒绝）
        if cid in state.entry_pending and fill.status in _TERMINAL_FILL_STATUSES:
            state.entry_pending.pop(cid, None)
            return

        # 平仓限价单成交（止盈达成）
        if cid == state.exit_cid and fill.status == FILL_FILLED:
            state.reset_position_state()
            return

        # 平仓限价单撤单 / 过期
        if cid == state.exit_cid and fill.status in _TERMINAL_FILL_STATUSES:
            state.exit_cid = None
            state.exit_price = 0.0
            return

        # 市价止损单 / 尾盘强平成交 → 持仓清零
        if fill.status == FILL_FILLED and fill.offset == OFFSET_CLOSE:
            state.reset_position_state()
            state.sl_in_flight = False

    # ──────────────────────────────────────────────────────────────────
    # on_bar 分派：纯函数决策 + 副作用调用
    # ──────────────────────────────────────────────────────────────────

    def _dispatch_entries(self, bar: Bar) -> List[Signal]:
        """空仓时分派：维护已有入场挂单（撤单）或挂新一组多层入场单。"""
        state = self._state
        signals: List[Signal] = []

        # 已有入场挂单：vol 收缩则撤掉
        if state.entry_pending:
            if not check_keep_pending_legs(
                self._indicators.vol_ratio, self._params
            ):
                for cid in list(state.entry_pending):
                    self.cancel_order(self.symbol, cid)
                state.last_cancel_entry_bar = state.bar_idx
            return signals

        # 没有 entry pending — 是否可以挂新一组
        if not check_can_remit_legs(
            bar_time              = bar.timestamp.time(),
            bar_idx               = state.bar_idx,
            last_cancel_entry_bar = state.last_cancel_entry_bar,
            params                = self._params,
        ):
            return signals

        mid = self._indicators.mid
        if mid is None:
            return signals

        plan = plan_entry_legs(
            mid       = mid,
            short_atr = self._indicators.short_atr,
            params    = self._params,
        )
        return self._materialize_entry_plan(bar, plan)

    def _dispatch_exit(self, bar: Bar) -> List[Signal]:
        """持仓非空时分派：根据 ``plan_exit_decision`` 结果落地动作。"""
        state = self._state
        if state.sl_in_flight or state.entry_bar_idx is None:
            return []

        plan = plan_exit_decision(
            direction          = state.position_direction,
            entry_price        = state.entry_price,
            entry_bar_idx      = state.entry_bar_idx,
            bar_idx            = state.bar_idx,
            bar_close          = float(bar.close),
            short_atr          = self._indicators.short_atr,
            has_pending_tp     = state.exit_cid is not None,
            last_tp_adjust_bar = state.last_tp_adjust_bar,
            tp_adjust_times    = state.tp_adjust_times,
            params             = self._params,
        )
        return self._materialize_exit_plan(bar, plan)

    def _dispatch_force_close(self, bar: Bar) -> List[Signal]:
        """``close_time`` 后：撤所有未成交挂单 + 持仓发市价强平。"""
        state = self._state
        for cid in list(state.entry_pending):
            self.cancel_order(self.symbol, cid)
        if state.exit_cid is not None:
            self.cancel_order(self.symbol, state.exit_cid)

        signals: List[Signal] = []
        if (
            not self.position.is_flat
            and state.position_direction != 0
            and not state.sl_in_flight
        ):
            state.sl_in_flight = True
            signals.append(self._make_close_signal(
                bar,
                direction   = -state.position_direction,
                price       = None,
                cid         = self.new_client_order_id(prefix="FC"),
                order_type  = ORDER_MARKET,
                signal_kind = SIGNAL_FORCE_CLOSE,
                tag         = "尾盘强平",
            ))
        return signals

    # ──────────────────────────────────────────────────────────────────
    # Plan 落地：把 decision 返回值翻译成 Signal + 副作用调用
    # ──────────────────────────────────────────────────────────────────

    def _materialize_entry_plan(self, bar: Bar, plan: EntryPlan) -> List[Signal]:
        """把 ``EntryPlan.legs`` 逐笔包成 ``Signal``，同时登记到 ``CarryState.entry_pending``。"""
        if plan.is_empty:
            return []

        state = self._state
        signals: List[Signal] = []
        for i, (direction, price) in enumerate(plan.legs):
            prefix = f"OL{i // 2}" if direction == +1 else f"OS{i // 2}"
            cid = self.new_client_order_id(prefix=prefix)
            state.entry_pending[cid] = {"direction": direction, "price": price}
            signals.append(self._make_entry_signal(bar, direction, price, cid))
        return signals

    def _materialize_exit_plan(self, bar: Bar, plan: ExitPlan) -> List[Signal]:
        """根据 ``ExitPlan.action`` 落地：撤旧（如需）+ 挂新（如需）。"""
        state = self._state

        if plan.action == "noop":
            return []

        if plan.action == "market_stop":
            if state.exit_cid is not None:
                self.cancel_order(self.symbol, state.exit_cid)
            state.sl_in_flight = True
            return [self._make_close_signal(
                bar,
                direction   = plan.direction,
                price       = None,
                cid         = self.new_client_order_id(prefix="SL"),
                order_type  = ORDER_MARKET,
                signal_kind = SIGNAL_STOP_LOSS,
                tag         = plan.tag,
            )]

        if plan.action == "limit_tp":
            cid = self.new_client_order_id(prefix="TP")
            state.exit_cid = cid
            state.exit_price = float(plan.price)
            return [self._make_close_signal(
                bar,
                direction   = plan.direction,
                price       = plan.price,
                cid         = cid,
                order_type  = ORDER_LIMIT,
                signal_kind = SIGNAL_TAKE_PROFIT,
                tag         = plan.tag,
            )]

        if plan.action == "adjust_tp":
            # 撤旧 → 同 bar 内引擎先 drain_cancels 再 submit_pending，因此本 bar
            # 立即重挂是安全的。本地把 exit_cid 置 None，避免 on_fill(FILL_CANCELLED)
            # 回调与新单的 cid 串扰。
            if state.exit_cid is not None:
                self.cancel_order(self.symbol, state.exit_cid)
                state.exit_cid = None

            state.tp_adjust_times += 1
            state.last_tp_adjust_bar = state.bar_idx
            new_cid = self.new_client_order_id(prefix=f"TPA{state.tp_adjust_times}")
            state.exit_cid = new_cid
            state.exit_price = float(plan.price)
            return [self._make_close_signal(
                bar,
                direction   = plan.direction,
                price       = plan.price,
                cid         = new_cid,
                order_type  = ORDER_LIMIT,
                signal_kind = SIGNAL_TAKE_PROFIT,
                tag         = plan.tag,
            )]

        return []

    # ──────────────────────────────────────────────────────────────────
    # Signal 构造工具
    # ──────────────────────────────────────────────────────────────────

    def _make_entry_signal(
        self, bar: Bar, direction: int, price: float, cid: str,
    ) -> Signal:
        return Signal(
            symbol           = bar.symbol,
            action_datetime  = bar.timestamp,
            bar_datetime     = bar.timestamp,
            signal_kind      = SIGNAL_ENTRY,
            direction        = int(direction),
            offset           = OFFSET_OPEN,
            order_type       = ORDER_LIMIT,
            session          = SESSION_NAME,
            tag              = "多层限价入场",
            price            = float(price),
            volume_hint      = int(self._params.entry_volume),
            client_order_id  = cid,
        )

    def _make_close_signal(
        self,
        bar: Bar,
        *,
        direction: int,
        price: Optional[float],
        cid: str,
        order_type: str,
        signal_kind: str,
        tag: str,
    ) -> Signal:
        vol = (
            self.position.short_volume if direction == 1
            else self.position.long_volume
        )
        return Signal(
            symbol           = bar.symbol,
            action_datetime  = bar.timestamp,
            bar_datetime     = bar.timestamp,
            signal_kind      = signal_kind,
            direction        = int(direction),
            offset           = OFFSET_CLOSE,
            order_type       = order_type,
            session          = SESSION_NAME,
            tag              = tag,
            price            = price,
            volume_hint      = int(vol) if vol > 0 else int(self._params.entry_volume),
            client_order_id  = cid,
        )


class _BarLike:
    """on_init 预热段把 ``own_bars.itertuples()`` 行包成最小 Bar 形态以喂入
    ``IndicatorWindow.update``。仅暴露 close/high/low 三个属性。
    """
    __slots__ = ("close", "high", "low")

    def __init__(self, close: float, high: float, low: float):
        self.close = float(close)
        self.high = float(high)
        self.low = float(low)


__all__ = ["Strategy", "STRATEGY_NAME"]
