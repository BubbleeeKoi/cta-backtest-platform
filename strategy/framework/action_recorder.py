"""
framework/action_recorder.py  ——  策略 ↔ 撮合层的动作事件流落盘

用途
    比 ``signals.csv`` / ``trades.csv`` 更细一层的事件流，按时间线记录：
        - 每笔进到撮合层的订单（``place_order``）
        - 每次策略发起的撤单（``cancel_request``）
        - 每次撮合层返回的成交回报（``fill_filled`` / ``fill_cancelled`` /
          ``fill_expired`` / ``fill_rejected`` / ``fill_partial``）
        - 组合层因 cap 命中丢弃的开仓 signal（``cap_rejected``）

    主要面向用了 ``cancel_order`` / 多挂单管理的策略，可视化"挂 → 撤 → 重挂
    → 成交"全过程；对未挂单的简单策略仅生成一份扁平 fill 流水，开销忽略。

为什么不在策略层做
    撤单 / 成交事件来自撮合层；策略只能看到自己发起的撤单意图，看不到
    "撤单是否真的命中""撤单后多久才成交"等顺序。在引擎层埋点能拿到
    最完整的事件链且对策略零侵入。

落盘 schema（CSV，columns 固定，跨数据源稳定）
    ts, strategy_id, symbol, event,
    client_order_id, order_id, signal_id,
    direction, offset, order_type, signal_kind,
    price, volume, fill_price, fill_volume,
    tag, reject_reason, pending_after

字段说明
    ts            事件发生的时间戳；place_order/fill 用 ts，cancel_request 用
                  策略调用 cancel_order 的 bar 时间
    event         place_order | cancel_request | fill_<status>
    client_order_id   策略侧 ID（策略调 ``new_client_order_id`` 分配）
    order_id      框架内部 ID（撮合层视角；cancel_request 时为 None）
    signal_id     策略 Signal 的 uuid；fill 时透传自 order
    price, volume order 提交时的限价/手数；fill 时 None
    fill_price, fill_volume   仅 fill 事件填充
    pending_after 该 symbol 当前 pending 队列长度的快照（看"同方向多笔
                  并存"瞬间的关键指标）。
                  - place_order / cancel_request：事件落地之前的快照
                  - fill_*：事件落地之后的快照

线程安全
    本类**非线程安全**。引擎主循环单线程，无需加锁。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .types import Fill, Order, Signal

_COLUMNS: tuple[str, ...] = (
    "ts", "strategy_id", "symbol", "event",
    "client_order_id", "order_id", "signal_id",
    "direction", "offset", "order_type", "signal_kind",
    "price", "volume", "fill_price", "fill_volume",
    "tag", "reject_reason", "pending_after",
)


@dataclass
class _Row:
    """避免每次 record 都构造 dict；落盘时统一组装。"""
    ts: pd.Timestamp
    strategy_id: str
    symbol: str
    event: str
    client_order_id: Optional[str]
    order_id: Optional[str]
    signal_id: Optional[str]
    direction: Optional[int]
    offset: Optional[str]
    order_type: Optional[str]
    signal_kind: Optional[str]
    price: Optional[float]
    volume: Optional[int]
    fill_price: Optional[float]
    fill_volume: Optional[int]
    tag: Optional[str]
    reject_reason: Optional[str]
    pending_after: Optional[int]


class ActionRecorder:
    """记录策略 ↔ 撮合层的所有动作事件；可落盘成 CSV。

    用法（回测端）::

        recorder = ActionRecorder()
        engine = BacktestEngine(..., action_recorder=recorder)
        engine.run()
        recorder.save(Path("output/actions/actions_run.csv"))
    """

    def __init__(self) -> None:
        self._rows: List[_Row] = []

    # ── 采集 ─────────────────────────────────────────────────────────

    def record_place(
        self,
        order: Order,
        ts: pd.Timestamp,
        pending_after: Optional[int] = None,
    ) -> None:
        """记录一笔进入撮合层的 order。"""
        self._rows.append(_Row(
            ts              = ts,
            strategy_id     = order.strategy_id,
            symbol          = order.symbol,
            event           = "place_order",
            client_order_id = order.client_order_id,
            order_id        = order.order_id,
            signal_id       = order.signal_id,
            direction       = int(order.direction),
            offset          = order.offset,
            order_type      = order.order_type,
            signal_kind     = None,
            price           = order.price,
            volume          = int(order.volume),
            fill_price      = None,
            fill_volume     = None,
            tag             = order.tag,
            reject_reason   = None,
            pending_after   = pending_after,
        ))

    def record_cancel_request(
        self,
        strategy_id: str,
        symbol: str,
        ts: pd.Timestamp,
        client_order_id: str,
        pending_before: Optional[int] = None,
    ) -> None:
        """记录一次策略发起的撤单请求（在 matcher.cancel 调用之前埋点）。"""
        self._rows.append(_Row(
            ts              = ts,
            strategy_id     = strategy_id,
            symbol          = symbol,
            event           = "cancel_request",
            client_order_id = client_order_id,
            order_id        = None,
            signal_id       = None,
            direction       = None,
            offset          = None,
            order_type      = None,
            signal_kind     = None,
            price           = None,
            volume          = None,
            fill_price      = None,
            fill_volume     = None,
            tag             = None,
            reject_reason   = None,
            pending_after   = pending_before,
        ))

    def record_cap_reject(
        self,
        signal: Signal,
        ts: pd.Timestamp,
        cap_open_count: int,
        max_stack: int,
    ) -> None:
        """记录一个被组合层 cap 命中丢弃的开仓 signal。

        Args:
            signal           被丢弃的 Signal（offset=OPEN）。
            ts               事件时间（一般 = signal.action_datetime）。
            cap_open_count   命中 cap 之前 ``(symbol, direction)`` 桶里已有的未平
                             仓位数 + 同 bar 已 accept 的同桶 signal 计数。
            max_stack        当前组合配置的 cap 阈值（如默认 2）。
        """
        self._rows.append(_Row(
            ts              = ts,
            strategy_id     = signal.strategy_id,
            symbol          = signal.symbol,
            event           = "cap_rejected",
            client_order_id = signal.client_order_id,
            order_id        = None,
            signal_id       = signal.signal_id,
            direction       = int(signal.direction),
            offset          = signal.offset,
            order_type      = signal.order_type,
            signal_kind     = signal.signal_kind,
            price           = signal.price,
            volume          = None,
            fill_price      = None,
            fill_volume     = None,
            tag             = signal.tag,
            reject_reason   = f"cap_full:open={cap_open_count}/max={max_stack}",
            pending_after   = cap_open_count,
        ))

    def record_fill(
        self,
        fill: Fill,
        ts: pd.Timestamp,
        pending_after: Optional[int] = None,
    ) -> None:
        """记录一次撮合反馈（filled / cancelled / expired / rejected / partial）。"""
        self._rows.append(_Row(
            ts              = ts,
            strategy_id     = fill.strategy_id,
            symbol          = fill.symbol,
            event           = f"fill_{fill.status}",
            client_order_id = fill.client_order_id,
            order_id        = fill.order_id,
            signal_id       = fill.signal_id,
            direction       = int(fill.direction),
            offset          = fill.offset,
            order_type      = None,
            signal_kind     = None,
            price           = None,
            volume          = None,
            fill_price      = fill.fill_price,
            fill_volume     = int(fill.fill_volume),
            tag             = fill.tag,
            reject_reason   = fill.reject_reason,
            pending_after   = pending_after,
        ))

    # ── 输出 ─────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=list(_COLUMNS))
        rows = [
            {
                "ts":              r.ts,
                "strategy_id":     r.strategy_id,
                "symbol":          r.symbol,
                "event":           r.event,
                "client_order_id": r.client_order_id,
                "order_id":        r.order_id,
                "signal_id":       r.signal_id,
                "direction":       r.direction,
                "offset":          r.offset,
                "order_type":      r.order_type,
                "signal_kind":     r.signal_kind,
                "price":           r.price,
                "volume":          r.volume,
                "fill_price":      r.fill_price,
                "fill_volume":     r.fill_volume,
                "tag":             r.tag,
                "reject_reason":   r.reject_reason,
                "pending_after":   r.pending_after,
            }
            for r in self._rows
        ]
        df = pd.DataFrame(rows, columns=list(_COLUMNS))
        return df.sort_values(
            ["strategy_id", "symbol", "ts"], kind="mergesort"
        ).reset_index(drop=True)

    def save(self, path: Path | str) -> Path:
        """落盘 CSV；自动建目录。返回最终 Path。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        df.to_csv(p, index=False, encoding="utf-8-sig")
        return p

    def __len__(self) -> int:
        return len(self._rows)

    def clear(self) -> None:
        self._rows.clear()


__all__ = ["ActionRecorder"]
