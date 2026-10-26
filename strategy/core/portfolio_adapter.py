"""
core/portfolio_adapter.py  ——  组合层（实盘撮合层等价物）

把多策略产生的 Signal 流，按组合规则汇成最终落地的 Order 流。

提供 4 个内置实现:
    PassThroughAdapter        全部直通；每个 Signal 单独按 sizer 决定手数
    CappedCapitalAdapter      按 per_strategy_capital + per_symbol_capital_cap 缩放
    ConflictDedupAdapter      同品种多策略同时段的同向叠加 / 反向抵消
    CappedPositionAdapter     同 (symbol, direction) 任一时刻最多 max_stack 个未平
                              仓位；超出按 strategy_order 顺位丢弃（V0.3 语义）

实盘里这一层是撮合执行模块的一部分；接口签名与本类一致即可。
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd

from framework.action_recorder import ActionRecorder
from framework.types import (
    FILL_FILLED,
    FILL_PARTIAL,
    FILL_REJECTED,
    OFFSET_OPEN,
    ORDER_EXACT,
    ORDER_LIMIT,
    Fill,
    Order,
    Signal,
)

from .sizing import BaseSizer, NotionalSizer


# ──────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────

class BasePortfolioAdapter:
    """组合层抽象基类。"""

    def __init__(self, contract_info_by_symbol: Dict[str, dict]) -> None:
        self._ci = contract_info_by_symbol

    def process(
        self,
        ts: pd.Timestamp,
        signals_by_strategy: Dict[str, List[Signal]],
        ref_price_by_symbol: Dict[str, float],
    ) -> List[Order]:
        raise NotImplementedError

    def on_fill(self, fill: Fill) -> None:
        """成交回灌钩子。

        引擎在每笔 fill 回灌给 strategy 之前先调本钩子，让组合层 adapter
        有机会维护其内部状态（如 ``CappedPositionAdapter.open_positions``）。
        默认实现为无操作；只有需要持仓视图的 adapter 需要 override。
        """
        return

    def take_pending_drop_fills(self) -> List[Fill]:
        """取出本次 ``process()`` 累积的"被组合层 drop 的 signal"对应的合成 fill。

        组合层（如 ``CappedPositionAdapter``）在 cap 命中时丢弃 signal；为保持
        策略本地状态（如 ``_in_flight`` 类去重 gate）与"该 signal 永远不会被
        撮合"的事实一致，引擎在 ``process()`` 之后立刻消费本队列，把这些
        合成 fill（status=FILL_REJECTED）当成普通 fill 回灌给策略。

        默认返回空列表。
        """
        return []

    # ── 工具 ──────────────────────────────────────────────────────────

    def _make_order(
        self,
        signal: Signal,
        volume: int,
        ref_price: float,
    ) -> Order:
        # ORDER_LIMIT / ORDER_EXACT 都必须带价格
        if signal.order_type in (ORDER_LIMIT, ORDER_EXACT):
            order_price = signal.price
        else:
            order_price = None
        return Order(
            order_id        = uuid.uuid4().hex[:8],
            signal_id       = signal.signal_id,
            strategy_id     = signal.strategy_id,
            symbol          = signal.symbol,
            contract        = signal.symbol,  # 品种级回测：合约即品种
            direction       = signal.direction,
            offset          = signal.offset,
            order_type      = signal.order_type,
            volume          = int(volume),
            price           = order_price,
            submit_datetime = signal.action_datetime,
            session         = signal.session,
            tag             = signal.tag,
            client_order_id = signal.client_order_id,
        )

    def _point_of(self, symbol: str) -> float:
        return float(self._ci.get(symbol, {}).get("point", 10))


# ──────────────────────────────────────────────────────────────────────────
# PassThrough
# ──────────────────────────────────────────────────────────────────────────

class PassThroughAdapter(BasePortfolioAdapter):
    """
    最小直通版：每个 Signal 用对应策略的 sizer 单独定手数，不做任何过滤。

    构造:
        adapter = PassThroughAdapter(
            contract_info_by_symbol = {...},
            sizer_by_strategy       = {"jerome": NotionalSizer(1_000_000), ...},
        )
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        sizer_by_strategy: Dict[str, BaseSizer],
    ) -> None:
        super().__init__(contract_info_by_symbol)
        self._sizers = sizer_by_strategy

    def process(
        self,
        ts: pd.Timestamp,
        signals_by_strategy: Dict[str, List[Signal]],
        ref_price_by_symbol: Dict[str, float],
    ) -> List[Order]:
        orders: List[Order] = []
        for strategy, signals in signals_by_strategy.items():
            sizer = self._sizers.get(strategy)
            if sizer is None:
                continue
            for sig in signals:
                ref_price = sig.price if sig.price else ref_price_by_symbol.get(sig.symbol, 0.0)
                if ref_price <= 0:
                    continue
                # 策略显式给手数（ORDER_EXACT 等场景）→ 直接用，跳过 sizer
                if sig.volume_hint is not None and sig.volume_hint > 0:
                    vol = int(sig.volume_hint)
                else:
                    # 开仓按 sizer 定手数；平仓也按 sizer 定（accountant 配对时 FIFO 兜底）
                    vol = sizer.calc_volume(ref_price, self._point_of(sig.symbol))
                if vol > 0:
                    orders.append(self._make_order(sig, vol, ref_price))
        return orders


# ──────────────────────────────────────────────────────────────────────────
# CappedCapital
# ──────────────────────────────────────────────────────────────────────────

class CappedCapitalAdapter(BasePortfolioAdapter):
    """
    资金限额版：在 PassThrough 基础上叠加：
        1. 每策略名义市值上限 = per_strategy_capital
        2. 每品种总名义市值上限 = per_symbol_capital_cap （跨所有策略）

    超限时按时间先后 FIFO 截单（后到的截手数或全单否决）。
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        per_strategy_capital: float,
        per_symbol_capital_cap: float,
        sizer_by_strategy: Dict[str, BaseSizer] | None = None,
    ) -> None:
        super().__init__(contract_info_by_symbol)
        self._per_strat_cap = float(per_strategy_capital)
        self._per_sym_cap   = float(per_symbol_capital_cap)
        # 默认每策略一个 NotionalSizer
        if sizer_by_strategy is None:
            self._sizers: Dict[str, BaseSizer] = {}
        else:
            self._sizers = dict(sizer_by_strategy)

    def _sizer_for(self, strategy: str) -> BaseSizer:
        if strategy not in self._sizers:
            self._sizers[strategy] = NotionalSizer(self._per_strat_cap)
        return self._sizers[strategy]

    def process(
        self,
        ts: pd.Timestamp,
        signals_by_strategy: Dict[str, List[Signal]],
        ref_price_by_symbol: Dict[str, float],
    ) -> List[Order]:
        orders: List[Order] = []
        used_by_symbol: Dict[str, float] = defaultdict(float)
        for strategy, signals in signals_by_strategy.items():
            sizer = self._sizer_for(strategy)
            for sig in signals:
                ref_price = sig.price if sig.price else ref_price_by_symbol.get(sig.symbol, 0.0)
                if ref_price <= 0:
                    continue
                point = self._point_of(sig.symbol)
                vol = (int(sig.volume_hint) if sig.volume_hint is not None and sig.volume_hint > 0
                       else sizer.calc_volume(ref_price, point))
                notional = vol * ref_price * point

                # 品种上限检查（仅 open 计入）
                if sig.offset == OFFSET_OPEN:
                    available = self._per_sym_cap - used_by_symbol[sig.symbol]
                    if available <= 0:
                        continue  # 该品种已打满，跳过
                    if notional > available:
                        # 按可用资金截手数
                        vol = max(0, int(available / (ref_price * point)))
                        if vol <= 0:
                            continue
                        notional = vol * ref_price * point
                    used_by_symbol[sig.symbol] += notional

                if vol > 0:
                    orders.append(self._make_order(sig, vol, ref_price))
        return orders


# ──────────────────────────────────────────────────────────────────────────
# ConflictDedup
# ──────────────────────────────────────────────────────────────────────────

class ConflictDedupAdapter(BasePortfolioAdapter):
    """
    各策略完全独立下单（stack）：每个策略的开仓/平仓信号互不干扰，
    行为上与 PassThroughAdapter 等价，但保留独立的 sizer_by_strategy 入口。
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        sizer_by_strategy: Dict[str, BaseSizer],
    ) -> None:
        super().__init__(contract_info_by_symbol)
        self._sizers = sizer_by_strategy

    def process(
        self,
        ts: pd.Timestamp,
        signals_by_strategy: Dict[str, List[Signal]],
        ref_price_by_symbol: Dict[str, float],
    ) -> List[Order]:
        orders: List[Order] = []
        for strategy, sigs in signals_by_strategy.items():
            sizer = self._sizers.get(strategy)
            if sizer is None:
                continue
            for sig in sigs:
                ref_price = sig.price if sig.price else ref_price_by_symbol.get(sig.symbol, 0.0)
                if ref_price <= 0:
                    continue
                vol = (int(sig.volume_hint) if sig.volume_hint is not None and sig.volume_hint > 0
                       else sizer.calc_volume(ref_price, self._point_of(sig.symbol)))
                if vol > 0:
                    orders.append(self._make_order(sig, vol, ref_price))
        return orders


# ──────────────────────────────────────────────────────────────────────────
# CappedPosition  ——  组合层"同 (sym, dir) 最多 N 个未平仓位"硬 cap
# ──────────────────────────────────────────────────────────────────────────

class CappedPositionAdapter(BasePortfolioAdapter):
    """同 ``(symbol, direction)`` 任一时刻最多 ``max_stack`` 个未平仓位的组合层。

    设计语义（与 V0.3 ``run_portfolio.py`` 等价）：
        - cap 仅约束**开仓** signal（``signal.is_open=True``）；
          close / 止损 / 止盈 / 强平等平仓 signal 永远透传。
        - 同 bar 内多策略同时对同一 ``(sym, dir)`` 发出开仓 signal 时，按
          ``strategy_order`` 升序（注册顺序，通常来自 strategies.yaml）依次评估：
          已有未平仓位 + 本 bar 已 accept 同桶 signal 计数 < max_stack 则 accept，
          否则丢弃并写 ``ActionRecorder.record_cap_reject``。
        - cap 桶状态由 ``on_fill`` 维护：fill_filled / fill_partial 的 OPEN 入栈、
          CLOSE 出栈；cancelled / expired / rejected 不影响（无真实持仓变化）。

    与 ``CappedCapitalAdapter`` 的区别：前者按"市值"做品种总额上限（单 bar 视角），
    本类按"未平仓位计数"做硬 cap（跨 bar 持仓视角），是 V0.3 ``max_stack`` 语义的
    直系实现，等价于"每策略 100 万 × cap=2 → 单方向最多 2 倍策略本金市值"。
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        sizer_by_strategy: Dict[str, BaseSizer],
        strategy_order: List[str],
        max_stack: int = 2,
        action_recorder: Optional[ActionRecorder] = None,
    ) -> None:
        super().__init__(contract_info_by_symbol)
        self._sizers = dict(sizer_by_strategy)
        self._strategy_order: List[str] = list(strategy_order)
        # 注册顺序 → 索引（同 bar tie-break 用）
        self._order_idx: Dict[str, int] = {
            s: i for i, s in enumerate(self._strategy_order)
        }
        if max_stack < 1:
            raise ValueError(f"max_stack 必须 >= 1，收到 {max_stack}")
        self._max_stack = int(max_stack)
        self._action_recorder = action_recorder

        # (symbol, direction) -> List[(strategy_id, client_order_id_or_order_id)]
        # 用 (strategy_id, ref_key) 唯一标识一个仓位；ref_key 优先 client_order_id，
        # 没有则用 order_id（部分策略不发 client_order_id）
        self._open_positions: Dict[Tuple[str, int], List[Tuple[str, str]]] = defaultdict(list)

        # 本次 process() 累积的"被 cap drop 的 signal"对应的合成 fill；
        # engine 在 process() 后立刻消费，回灌给策略以清理本地状态（如 _in_flight）。
        self._drop_fills_pending: List[Fill] = []

    # ── 配置 / 监控 ─────────────────────────────────────────────────────

    @property
    def max_stack(self) -> int:
        return self._max_stack

    def open_count(self, symbol: str, direction: int) -> int:
        """快照查询：当前 ``(symbol, direction)`` 已有的未平仓位数。"""
        return len(self._open_positions.get((symbol, int(direction)), []))

    def open_positions_snapshot(self) -> Dict[Tuple[str, int], List[Tuple[str, str]]]:
        """返回 open_positions 浅拷贝（调试 / 测试用）。"""
        return {k: list(v) for k, v in self._open_positions.items()}

    def take_pending_drop_fills(self) -> List[Fill]:
        """取出 process() 期间累积的 cap-drop 合成 fill。返回后清空内部队列。"""
        out, self._drop_fills_pending = self._drop_fills_pending, []
        return out

    # ── 撮合层回灌钩子 ──────────────────────────────────────────────────

    def on_fill(self, fill: Fill) -> None:
        """成交回灌：维护 open_positions 入 / 出栈。

        策略：
            - 只有 status ∈ {filled, partial} 才影响持仓（cancelled/expired/rejected 不动）
            - offset=OPEN  → 入栈
            - offset=CLOSE / close_today / close_yesterday → 出栈

        出栈匹配规则：FIFO；优先按 (strategy_id, client_order_id) 命中，
        否则按 (strategy_id, order_id) 命中，否则按 strategy_id 命中第一笔。
        """
        if fill.status not in (FILL_FILLED, FILL_PARTIAL):
            return
        if fill.fill_volume <= 0:
            return

        key = (fill.symbol, int(fill.direction)) if fill.offset == OFFSET_OPEN \
              else (fill.symbol, -int(fill.direction))
        # 注：close 的 direction 表示"平掉哪边"，期货语义下 +1=买平空、-1=卖平多；
        #     因此 close 的"被平仓位"方向 = -fill.direction。

        if fill.offset == OFFSET_OPEN:
            ref_key = fill.client_order_id or fill.order_id
            self._open_positions[key].append((fill.strategy_id, ref_key))
            return

        # close 出栈：按 (strategy_id, ref_key) 优先匹配；找不到回退到 strategy_id 首笔
        stack = self._open_positions.get(key)
        if not stack:
            return
        ref_key = fill.client_order_id or fill.order_id
        for i, (sid, rk) in enumerate(stack):
            if sid == fill.strategy_id and rk == ref_key:
                stack.pop(i)
                break
        else:
            # ref_key 没命中：按 strategy_id 找最早一笔
            for i, (sid, _rk) in enumerate(stack):
                if sid == fill.strategy_id:
                    stack.pop(i)
                    break
        if not stack:
            self._open_positions.pop(key, None)

    # ── 主流程 ──────────────────────────────────────────────────────────

    def process(
        self,
        ts: pd.Timestamp,
        signals_by_strategy: Dict[str, List[Signal]],
        ref_price_by_symbol: Dict[str, float],
    ) -> List[Order]:
        """同 bar 信号合并 + cap 检查 + 转 Order。"""
        # 1) 拍平为时序列表。
        # tie-break 规则：
        #   - 跨策略：按 strategy_order（yaml 注册顺序）升序
        #   - 同策略内：保持 ``strategy.on_bar`` 返回 List[Signal] 的原顺序
        #     （batch/stream 两路径 per-strategy 签名已由 verify_streaming 保证等价）
        # 注意：不引入 ``signal_id`` 作 tie-break，因为它是 uuid（运行时随机），
        #       会破坏跨进程 / 跨调用的字节一致性。
        flat: List[Tuple[int, Signal]] = []
        for sid in sorted(
            signals_by_strategy.keys(),
            key=lambda x: self._order_idx.get(x, len(self._order_idx) + hash(x) % 1000),
        ):
            idx = self._order_idx.get(sid, len(self._order_idx) + hash(sid) % 1000)
            for sig in signals_by_strategy[sid]:
                flat.append((idx, sig))

        orders: List[Order] = []
        # 本 bar 已 accept 的 (sym, dir) 同桶 open 计数（叠加在 open_positions 之上）
        same_bar_open: Dict[Tuple[str, int], int] = defaultdict(int)

        for _, sig in flat:
            sizer = self._sizers.get(sig.strategy_id)
            if sizer is None:
                continue
            ref_price = sig.price if sig.price else ref_price_by_symbol.get(sig.symbol, 0.0)
            if ref_price <= 0:
                continue

            # 平仓 signal：永远放行（不参与 cap）
            if not sig.is_open:
                if sig.volume_hint is not None and sig.volume_hint > 0:
                    vol = int(sig.volume_hint)
                else:
                    vol = sizer.calc_volume(ref_price, self._point_of(sig.symbol))
                if vol > 0:
                    orders.append(self._make_order(sig, vol, ref_price))
                continue

            # 开仓 signal：cap 检查
            key = (sig.symbol, int(sig.direction))
            curr_open = len(self._open_positions.get(key, [])) + same_bar_open[key]
            if curr_open >= self._max_stack:
                # 命中 cap → 丢弃 + 落 actions.csv + 合成 FILL_REJECTED 回灌
                # 让策略清理 ``_in_flight`` 类本地状态（V0.3 中策略本身没有这类
                # gate，所以默认行为是 transparent drop；本框架内多个策略带
                # _in_flight 自我节流，必须 echo 一次 reject 给策略保持状态一致）。
                if self._action_recorder is not None:
                    self._action_recorder.record_cap_reject(
                        signal=sig, ts=ts,
                        cap_open_count=curr_open, max_stack=self._max_stack,
                    )
                self._drop_fills_pending.append(Fill(
                    fill_id        = "",
                    order_id       = "",
                    signal_id      = sig.signal_id,
                    strategy_id    = sig.strategy_id,
                    symbol         = sig.symbol,
                    contract       = sig.symbol,
                    status         = FILL_REJECTED,
                    fill_datetime  = ts,
                    fill_price     = None,
                    fill_volume    = 0,
                    direction      = int(sig.direction),
                    offset         = sig.offset,
                    commission     = 0.0,
                    session        = sig.session,
                    reject_reason  = f"cap_full:open={curr_open}/max={self._max_stack}",
                    tag            = sig.tag,
                    client_order_id= sig.client_order_id,
                ))
                continue

            # 接受：转 Order
            if sig.volume_hint is not None and sig.volume_hint > 0:
                vol = int(sig.volume_hint)
            else:
                vol = sizer.calc_volume(ref_price, self._point_of(sig.symbol))
            if vol > 0:
                orders.append(self._make_order(sig, vol, ref_price))
                same_bar_open[key] += 1

        return orders


# ──────────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────────

def build_adapter(
    adapter_type: str,
    contract_info_by_symbol: Dict[str, dict],
    sizer_by_strategy: Dict[str, BaseSizer],
    config: dict | None = None,
) -> BasePortfolioAdapter:
    """根据 type 字符串构造 adapter。"""
    config = config or {}
    t = adapter_type.lower()
    if t == "passthrough":
        return PassThroughAdapter(contract_info_by_symbol, sizer_by_strategy)
    if t in ("capped_capital", "capped"):
        return CappedCapitalAdapter(
            contract_info_by_symbol,
            per_strategy_capital   = config.get("per_strategy_capital",   1_000_000),
            per_symbol_capital_cap = config.get("per_symbol_capital_cap", 3_000_000),
            sizer_by_strategy      = sizer_by_strategy,
        )
    if t in ("conflict_dedup", "dedup"):
        return ConflictDedupAdapter(
            contract_info_by_symbol,
            sizer_by_strategy = sizer_by_strategy,
        )
    if t in ("capped_position", "portfolio_combo"):
        strategy_order = config.get("strategy_order")
        if not strategy_order:
            raise ValueError("capped_position adapter 需要 config['strategy_order']")
        return CappedPositionAdapter(
            contract_info_by_symbol = contract_info_by_symbol,
            sizer_by_strategy       = sizer_by_strategy,
            strategy_order          = list(strategy_order),
            max_stack               = int(config.get("max_stack", 2)),
            action_recorder         = config.get("action_recorder"),
        )
    raise ValueError(f"未知 adapter type: {adapter_type}")
