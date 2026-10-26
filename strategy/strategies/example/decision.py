"""
jerome/decision.py  ——  挂单 / 撤单决策（纯函数）

返回结构:
    ``EntryPlan``     ：一组待挂的多层入场限价单（多空各 ``n_legs`` 层）
    ``ExitPlan``      ：一笔平仓决策（限价止盈 / 调整止盈 / 市价止损 / 强平）

成交语义:
    - 入场限价单：在 ``mid ± (i+1)·leg_step_atr·short_atr`` 上挂；同方向多层并存
    - 平仓限价单：``entry_price ± tp_atr·short_atr``；动态调整时逐步收窄目标距离
    - 市价止损：触发后立即撤回未成交的平仓限价单，再发市价单平仓

纯函数只决定"要不要"和"按什么价"；真正的 ``self.cancel_order``
/ ``self.new_client_order_id`` / 生成 ``Signal`` 由 ``strategy.py`` 完成。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .filters import (
    check_need_force_stop,
    check_should_adjust_tp,
)
from .params import StrategyParams


# ──────────────────────────────────────────────────────────────────────────
# 返回值
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class EntryPlan:
    """一组待挂的多层入场限价单。

    ``legs[i] = (direction, price)``；多空各 ``n_legs`` 层，按价格优先撮合。
    """

    legs: List[Tuple[int, float]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.legs


# 平仓动作：
#   "limit_tp"     新挂初始止盈限价单
#   "adjust_tp"    撤回旧止盈单 + 挂新的（更激进的）止盈限价单
#   "market_stop"  撤回旧止盈单 + 发市价止损单
#   "force_close"  撤所有未成交挂单 + 市价强平（尾盘）
#   "noop"         不动作
@dataclass
class ExitPlan:
    """一笔平仓决策。"""

    action: str = "noop"
    direction: int = 0           # 平仓方向（+1 平空 / -1 平多）
    price: Optional[float] = None  # market_stop / force_close 为 None
    tag: str = ""                 # 写入 Signal.tag → trades.csv 的 close_reason


# ──────────────────────────────────────────────────────────────────────────
# 入场决策
# ──────────────────────────────────────────────────────────────────────────

def plan_entry_legs(
    mid: float, short_atr: float, params: StrategyParams,
) -> EntryPlan:
    """以 ``mid`` 为中轴，多空各挂 ``n_legs`` 层限价单。

    第 i 层价格 = ``mid ± (i+1) · leg_step_atr · short_atr``。
    """
    if short_atr <= 0:
        return EntryPlan()

    legs: List[Tuple[int, float]] = []
    for i in range(params.n_legs):
        step = (i + 1) * params.leg_step_atr * short_atr
        legs.append((+1, mid - step))  # 买入限价：mid 下方
        legs.append((-1, mid + step))  # 卖出限价：mid 上方
    return EntryPlan(legs=legs)


# ──────────────────────────────────────────────────────────────────────────
# 平仓决策（持仓非空时调用）
# ──────────────────────────────────────────────────────────────────────────

def plan_exit_decision(
    direction: int,
    entry_price: float,
    entry_bar_idx: int,
    bar_idx: int,
    bar_close: float,
    short_atr: float,
    has_pending_tp: bool,
    last_tp_adjust_bar: int,
    tp_adjust_times: int,
    params: StrategyParams,
) -> ExitPlan:
    """持仓管理决策（优先级从高到低）：

    1. **market_stop**：浮亏 ≥ ``sl_atr·ATR`` 或 持仓 ≥ ``sl_max_hold_bars`` 根
       → 撤平仓单 + 市价止损（最强）
    2. **limit_tp**：还没挂止盈单 → 挂初始 ``entry_price ± tp_atr·ATR``
    3. **adjust_tp**：浮亏 ≥ ``tp_adjust_adverse_ratio·ATR`` 且通过节流 / 上限
       → 撤旧挂新（更激进）
    4. **noop**：保持现状
    """
    if short_atr <= 0:
        return ExitPlan()

    if check_need_force_stop(
        direction         = direction,
        entry_price       = entry_price,
        entry_bar_idx     = entry_bar_idx,
        bar_idx           = bar_idx,
        bar_close         = bar_close,
        short_atr         = short_atr,
        params            = params,
    ):
        return ExitPlan(
            action    = "market_stop",
            direction = -direction,
            price     = None,
            tag       = "撤单后市价止损",
        )

    if not has_pending_tp:
        tp_price = entry_price + direction * params.tp_atr * short_atr
        return ExitPlan(
            action    = "limit_tp",
            direction = -direction,
            price     = tp_price,
            tag       = "初始限价止盈",
        )

    if check_should_adjust_tp(
        direction          = direction,
        entry_price        = entry_price,
        bar_close          = bar_close,
        bar_idx            = bar_idx,
        last_tp_adjust_bar = last_tp_adjust_bar,
        tp_adjust_times    = tp_adjust_times,
        short_atr          = short_atr,
        params             = params,
    ):
        # 调整后的目标：把目标距开仓价缩短 (tp_adjust_times+1) × tp_adjust_step_ratio × ATR；
        # 不低于 0.1 × ATR（保留最小盈利目标，不会把止盈调成止损）
        shrink = (tp_adjust_times + 1) * params.tp_adjust_step_ratio * short_atr
        target_distance = max(
            params.tp_atr * short_atr - shrink,
            short_atr * 0.1,
        )
        new_tp_price = entry_price + direction * target_distance
        return ExitPlan(
            action    = "adjust_tp",
            direction = -direction,
            price     = new_tp_price,
            tag       = f"调整止盈第{tp_adjust_times + 1}次",
        )

    return ExitPlan()


__all__ = [
    "EntryPlan",
    "ExitPlan",
    "plan_entry_legs",
    "plan_exit_decision",
]
