"""
core/engine/signal_pipeline.py  ——  Signal → Order → Fill 流转辅助

为策略侧发出的 Signal 补全 ``signal_id`` / ``strategy_id``；撮合后回灌 Fill
给对应 slot 与 accountant。session / tag 元信息直接通过 Order → Fill 在
对象本身上透传，无需引擎额外维护映射表。

被 ``loop.BacktestEngine`` 调用；本模块不持有引擎状态，纯辅助函数。
"""
from __future__ import annotations

import uuid
from typing import List

from tqdm import tqdm

from framework.types import Signal


def tag_signal(sig: Signal, strategy_id: str) -> Signal:
    """为 Signal 补全 ``signal_id`` / ``strategy_id``。

    Signal 是 ``frozen`` dataclass，所以用 ``object.__setattr__`` 反写。
    """
    if not sig.signal_id:
        object.__setattr__(sig, "signal_id", uuid.uuid4().hex[:8])
    if not sig.strategy_id:
        object.__setattr__(sig, "strategy_id", strategy_id)
    return sig


def handle_fill(fill, slots: List, accountant) -> None:
    """通知所有匹配 strategy_id 的 slot.on_fill，并送入 accountant。

    session / tag 直接从 fill 自身读取（由 matcher 从 Order.session 透传）。
    """
    for slot in slots:
        if slot.strategy_id != fill.strategy_id:
            continue
        try:
            slot.instance.on_fill(fill)
        except Exception as e:
            tqdm.write(f"  [WARN] {slot.strategy_id}/{slot.symbol} on_fill 失败: {e}")
    accountant.on_fill(fill)
