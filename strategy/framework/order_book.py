"""
framework/order_book.py  ——  策略侧未成交订单簿（辅助类）

策略发出 Signal 后，框架/撮合会异步回灌 Fill。在 Fill 回来之前，
策略可以用 OrderBook 跟踪"已发但未完成"的 signal_id 集合，避免重复下单。

回测里是同步撮合，OrderBook 用处不大；实盘是异步流水时必须使用。
回测/实盘共用同一策略侧 API，策略代码无需区分两种场景。
"""
from __future__ import annotations

from typing import Dict, List

from .types import Fill, FILL_FILLED, FILL_REJECTED, FILL_CANCELLED, FILL_EXPIRED, Signal


class OrderBook:
    """
    策略侧未成交订单簿。

    用法:
        ob = OrderBook()
        sig = Signal(...)
        ob.submit(sig)             # 发单时登记
        ...
        ob.on_fill(fill)           # on_fill 时调用，自动从 pending 移除
        ob.is_pending(sig.signal_id)
        ob.pending_count()
    """

    def __init__(self) -> None:
        self._pending: Dict[str, Signal] = {}

    def submit(self, signal: Signal) -> None:
        self._pending[signal.signal_id] = signal

    def on_fill(self, fill: Fill) -> None:
        # 任何终态都从 pending 移除
        if fill.status in (FILL_FILLED, FILL_REJECTED, FILL_CANCELLED, FILL_EXPIRED):
            self._pending.pop(fill.signal_id, None)

    def is_pending(self, signal_id: str) -> bool:
        return signal_id in self._pending

    def pending_count(self) -> int:
        return len(self._pending)

    def pending_signals(self) -> List[Signal]:
        return list(self._pending.values())

    def clear(self) -> None:
        self._pending.clear()
