"""
jerome/filters.py  ——  入场 / 平仓闸门函数（纯函数）

四道闸门:
    check_can_remit_legs     是否可以重新挂入场单（时间窗 + 冷却间隔）
    check_keep_pending_legs  已有入场挂单是否需要继续保留（vol 收缩则撤）
    check_need_force_stop    持仓是否需要立刻撤平仓单 + 市价止损
    check_should_adjust_tp   止盈挂单是否需要"撤旧挂新"调整价位
"""
from __future__ import annotations

from datetime import time as dt_time

from .params import StrategyParams


def check_can_remit_legs(
    bar_time: dt_time,
    bar_idx: int,
    last_cancel_entry_bar: int,
    params: StrategyParams,
) -> bool:
    """空仓时是否允许挂新一组多层入场单。

    需同时满足：
        - 当前时间在 ``[observe_start, entry_cutoff)`` 区间内
        - 距上次撤入场单的 bar 间隔 ≥ ``rebar_interval``（防抖）
    """
    if bar_time < params.observe_start or bar_time >= params.entry_cutoff:
        return False
    if bar_idx - last_cancel_entry_bar < params.rebar_interval:
        return False
    return True


def check_keep_pending_legs(vol_ratio: float, params: StrategyParams) -> bool:
    """已有入场挂单是否需要继续保留。

    ``vol_ratio = ATR_short / ATR_long``；< ``vol_shrink_ratio`` 时认为波动
    收缩、当前挂单的预期触达可能性下降，应撤掉以避免次优成交。
    """
    return vol_ratio >= params.vol_shrink_ratio


def check_need_force_stop(
    direction: int,
    entry_price: float,
    entry_bar_idx: int,
    bar_idx: int,
    bar_close: float,
    short_atr: float,
    params: StrategyParams,
) -> bool:
    """持仓兜底止损判定：满足任一即触发"撤平仓单 + 市价止损"组合：

    - 浮亏 ≥ ``sl_atr × short_atr``
    - 持仓 bar 数 ≥ ``sl_max_hold_bars``
    """
    floating_loss = (entry_price - bar_close) * direction
    if floating_loss >= params.sl_atr * short_atr:
        return True
    held_bars = bar_idx - entry_bar_idx
    if held_bars >= params.sl_max_hold_bars:
        return True
    return False


def check_should_adjust_tp(
    direction: int,
    entry_price: float,
    bar_close: float,
    bar_idx: int,
    last_tp_adjust_bar: int,
    tp_adjust_times: int,
    short_atr: float,
    params: StrategyParams,
) -> bool:
    """止盈挂单是否需要撤旧挂新（调低目标）。

    需同时满足：
        - 距上次调整 ≥ ``tp_adjust_every_bars`` 根 bar（节流）
        - 已调整次数 < ``tp_adjust_max_times``（上限）
        - 当前浮亏 ≥ ``tp_adjust_adverse_ratio × short_atr``（值得调整）
    """
    if tp_adjust_times >= params.tp_adjust_max_times:
        return False
    if bar_idx - last_tp_adjust_bar < params.tp_adjust_every_bars:
        return False
    floating_loss = (entry_price - bar_close) * direction
    return floating_loss >= params.tp_adjust_adverse_ratio * short_atr


__all__ = [
    "check_can_remit_legs",
    "check_keep_pending_legs",
    "check_need_force_stop",
    "check_should_adjust_tp",
]
