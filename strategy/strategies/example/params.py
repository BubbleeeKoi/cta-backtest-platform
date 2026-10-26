"""
jerome/params.py  ——  策略参数 / 单日携带状态 / session 常量 / 策略名

- ``StrategyParams``    策略静态配置（dataclass(frozen=True)，由 yaml/dict 注入）
- ``CarryState``        单日 intraday 携带状态（跨 bar 推进，每日 reset 一次）
- ``SESSION_NAME``      Signal.session 与 trades.csv 时段名
- ``NAV_SESSION_NAMES`` Strategy.SESSION_NAMES 的 single source of truth
- ``STRATEGY_NAME``     策略品牌名
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import time as dt_time
from typing import Any, Dict, Optional

import pandas as pd


STRATEGY_NAME = "Jerome_PendingDemo"

# Signal.session 与 trades.csv 时段名；必须与 ``NAV_SESSION_NAMES`` 严格对齐，
# 否则 daily_pnl / portfolio NAV 聚合时按 SESSION_NAMES 查不到任何 trade，
# 导致全 0。
SESSION_NAME = "早盘"

NAV_SESSION_NAMES = [SESSION_NAME]


# ──────────────────────────────────────────────────────────────────────────
# 策略参数
# ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StrategyParams:
    """策略静态配置（参数扫描时直接构造新实例传入）。"""

    # ── 时间窗 ────────────────────────────────────────────────────────
    observe_start: dt_time = dt_time(9, 30)   # 开始挂入场单
    entry_cutoff:  dt_time = dt_time(11, 0)   # 不再新挂入场单（仅维护已有单 + 持仓）
    close_time:    dt_time = dt_time(14, 55)  # 尾盘强平 / 撤所有未成交单

    # ── 观察 / 指标窗口 ──────────────────────────────────────────────
    mid_lookback_bars: int = 20      # mid = 最近 N 根 close 的均值
    atr_short:         int = 10      # 短期 ATR（用于挂单步长 / 止盈止损）
    atr_long:          int = 30      # 长期 ATR（用于 vol_ratio）

    # ── 多层入场挂单 ──────────────────────────────────────────────────
    n_legs:        int = 3           # 单方向挂多少层（多空各 n_legs 层）
    leg_step_atr:  float = 0.6       # 相邻层之间的距离（短 ATR 倍数）
    entry_volume:  int = 1           # 每笔挂单手数（演示用 1 手）

    # ── 激活 / 撤单条件 ───────────────────────────────────────────────
    vol_shrink_ratio: float = 0.85   # ATR_short / ATR_long < 此值 → 撤入场挂单
    rebar_interval:   int = 10       # 撤单后至少等 N 根 bar 再重新挂入场单

    # ── 平仓限价（动态止盈）─────────────────────────────────────────
    tp_atr:                  float = 1.5    # 初始止盈距开仓价（短 ATR 倍数）
    tp_adjust_every_bars:    int = 10       # 每 N 根 bar 评估一次是否调低目标
    tp_adjust_adverse_ratio: float = 0.5    # 浮亏 ≥ 此 ATR 倍数 → 撤旧止盈单挂新
    tp_adjust_step_ratio:    float = 0.3    # 每次调低多少（短 ATR 倍数）
    tp_adjust_max_times:     int = 3        # 最多调整次数

    # ── 市价止损（撤单后强平）─────────────────────────────────────
    sl_max_hold_bars: int = 60       # 持仓 ≥ N 根仍未止盈 → 撤平仓单 + 市价止损
    sl_atr:           float = 2.0    # 浮亏 ≥ 此 ATR 倍数 → 立即撤平仓单 + 市价止损

    # 本策略不支持稀疏批量预算（用了 cancel_order），运行路径恒为 on_bar；
    # 此字段仅为参数注入兼容性保留，不参与任何分支判断。
    force_streaming: bool = False

    @classmethod
    def from_dict(cls, overrides: Optional[Dict[str, Any]]) -> "StrategyParams":
        """从 strategies.yaml 的 ``params:`` 段构造；未提供的字段沿用默认值。"""
        allowed = {f.name for f in fields(cls)}
        kept = {k: v for k, v in (overrides or {}).items() if k in allowed}
        return cls(**kept)


# ──────────────────────────────────────────────────────────────────────────
# 单日 intraday 携带状态
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class CarryState:
    """单日 intraday 状态（每天 ``reset_for_new_day`` 重建一次）。

    Pending 字典与持仓辅助状态都收敛在这里；持仓本身仍由 framework 维护的
    ``self.position`` 管理。
    """

    current_td: Optional[pd.Timestamp] = None
    bar_idx: int = 0
    last_cancel_entry_bar: int = -10_000

    # 入场预挂单：cid → {"direction": +1/-1, "price": float}
    # 同时存在多笔；某笔成交 / 撤单 / 过期 时从字典里删除
    entry_pending: Dict[str, Dict[str, float]] = field(default_factory=dict)

    # 持仓辅助状态（不替代 self.position；只记录入场时刻与开仓价）
    entry_bar_idx: Optional[int] = None
    entry_price: float = 0.0
    position_direction: int = 0  # +1 多 / -1 空 / 0 空仓

    # 平仓预挂单（同方向同时只有 1 笔；调整时撤旧挂新）
    exit_cid: Optional[str] = None
    exit_price: float = 0.0
    last_tp_adjust_bar: int = 0
    tp_adjust_times: int = 0

    # 市价止损单 in-flight 标记（避免同 bar 内连发多次市价止损）
    sl_in_flight: bool = False

    def reset_for_new_day(self, td: pd.Timestamp) -> None:
        """跨日清空当日 intraday 状态。"""
        self.current_td = td
        self.bar_idx = 0
        self.last_cancel_entry_bar = -10_000
        self.entry_pending.clear()
        self.reset_position_state()
        self.sl_in_flight = False

    def reset_position_state(self) -> None:
        """清空持仓相关辅助状态（持仓本身由 super().on_fill 维护）。"""
        self.position_direction = 0
        self.entry_bar_idx = None
        self.entry_price = 0.0
        self.exit_cid = None
        self.exit_price = 0.0
        self.tp_adjust_times = 0


__all__ = [
    "STRATEGY_NAME",
    "SESSION_NAME",
    "NAV_SESSION_NAMES",
    "StrategyParams",
    "CarryState",
]
