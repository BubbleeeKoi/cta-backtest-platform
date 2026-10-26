"""
core/matcher.py  ——  撮合器（回测专用）

接受 Order 列表 + 当前 bar 上下文，产出 Fill 列表。

成交规则（默认）:
    market: 以"下一根 bar 的 close"作为成交价（信号下达后撮合发生在下一根 bar 收盘）
    limit:  在后续 N 根 bar 内扫描价格触达，触达则按限价成交；
            否则当日尾盘强制以 close 成交（避免悬空）
    stop:   暂未实现，提交时按 market 处理

滑点:
    从 contract_info.slip 读取（tick 数），按 tick_size 转价格。
    买单加价、卖单减价。
    若 slip 缺失则默认 1.5 tick。

为了支持"市价 T+1 close"，撮合器需要"看下一根 bar"。
回测引擎驱动方式：调用 matcher.submit_pending(orders, ts) 把订单挂起，
然后调用 matcher.match_at(bar) 在下一根 bar 来到时做撮合。
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from framework.types import (
    FILL_CANCELLED,
    FILL_FILLED,
    FILL_EXPIRED,
    ORDER_EXACT,
    ORDER_LIMIT,
    ORDER_MARKET,
    ORDER_MARKET_0905,
    ORDER_STOP,
    Bar,
    Fill,
    Order,
)


@dataclass
class _PendingOrder:
    order: Order
    submit_ts: pd.Timestamp
    bars_waited: int = 0


class Matcher:
    """
    Bar 级撮合器。

    用法（由 BacktestEngine 调用）:
        matcher = Matcher(contract_info_by_symbol, limit_max_wait_bars=20)
        # 收到 strategy.on_bar 产生的 orders:
        matcher.submit_pending(orders, current_ts)
        # 下一根 bar 来到时：
        fills = matcher.match_at(next_bar)
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        limit_max_wait_bars: int = 20,
    ) -> None:
        self._ci = contract_info_by_symbol
        self._max_wait = int(limit_max_wait_bars)
        # 待撮合订单池：按 symbol 分组
        self._pending: Dict[str, List[_PendingOrder]] = defaultdict(list)

    # ── 查询 ──────────────────────────────────────────────────────────

    def pending_count(self, symbol: str) -> int:
        """``symbol`` 下当前未成交的 pending 单数量；用于可观测性埋点。"""
        return len(self._pending.get(symbol, []))

    # ── 提交 ──────────────────────────────────────────────────────────

    def submit_pending(self, orders: List[Order], ts: pd.Timestamp) -> List[Fill]:
        """
        提交订单。

        - ORDER_EXACT 立即按指定 price 成交，不入 pending 队列；返回的 Fill 列表
          供 engine 立即送给 strategy.on_fill / accountant。
        - 其它 order_type 入队，等下一根 bar 撮合。

        client_order_id 唯一性约束（fail-fast）:
            同一 symbol 下未成交挂单的 client_order_id 必须唯一；重复时（与已
            pending 的、或与本批次内的）立即抛 ValueError 中断本 bar。
            正常使用 self.new_client_order_id() 不可能触发，触发即策略 bug。
        """
        # 第一遍扫描：唯一性校验
        seen_in_batch: Dict[str, set] = defaultdict(set)
        for o in orders:
            if o.order_type == ORDER_EXACT or o.client_order_id is None:
                continue
            cid = o.client_order_id
            # 与已 pending 的对比
            if any(po.order.client_order_id == cid for po in self._pending[o.symbol]):
                raise ValueError(
                    f"重复 client_order_id: symbol={o.symbol} cid={cid} "
                    f"strategy={o.strategy_id}（同 symbol 下已存在未成交挂单；"
                    f"请用 self.new_client_order_id() 生成新 ID，不要复用旧 ID，"
                    f"也不要自己拼字符串）"
                )
            # 与本批次内的对比
            if cid in seen_in_batch[o.symbol]:
                raise ValueError(
                    f"重复 client_order_id: symbol={o.symbol} cid={cid} "
                    f"strategy={o.strategy_id}（同一批 Signal 内出现两次相同 cid）"
                )
            seen_in_batch[o.symbol].add(cid)

        # 第二遍：正式入队 / 立即成交
        immediate_fills: List[Fill] = []
        for o in orders:
            if o.order_type == ORDER_EXACT:
                immediate_fills.append(self._fill_exact(o))
            else:
                self._pending[o.symbol].append(_PendingOrder(order=o, submit_ts=ts))
        return immediate_fills

    def _fill_exact(self, order: Order) -> Fill:
        """ORDER_EXACT: 不滑点、不延迟、立即在 order.submit_datetime 成交。"""
        if order.price is None:
            return self._reject(order, "ORDER_EXACT 缺 price")
        return Fill(
            fill_id         = uuid.uuid4().hex[:8],
            order_id        = order.order_id,
            signal_id       = order.signal_id,
            strategy_id     = order.strategy_id,
            symbol          = order.symbol,
            contract        = order.contract,
            status          = FILL_FILLED,
            fill_datetime   = order.submit_datetime,
            fill_price      = float(order.price),
            fill_volume     = int(order.volume),
            direction       = order.direction,
            offset          = order.offset,
            commission      = 0.0,
            session         = order.session,
            reject_reason   = None,
            tag             = order.tag,
            client_order_id = order.client_order_id,
        )

    # ── 撤单：策略主动调用 ──────────────────────────────────────────

    def cancel(self, symbol: str, client_order_id: str) -> Optional[Fill]:
        """
        撤回 symbol 下指定 client_order_id 的 pending 单。

        - 找到匹配单：从 _pending[symbol] 移除，返回 FILL_CANCELLED 的 Fill
        - 找不到（已成交 / 已过期 / ID 不存在）：返回 None，不抛异常
        """
        pending_list = self._pending.get(symbol, [])
        for i, po in enumerate(pending_list):
            if po.order.client_order_id == client_order_id:
                order = po.order
                del pending_list[i]
                return Fill(
                    fill_id         = uuid.uuid4().hex[:8],
                    order_id        = order.order_id,
                    signal_id       = order.signal_id,
                    strategy_id     = order.strategy_id,
                    symbol          = order.symbol,
                    contract        = order.contract,
                    status          = FILL_CANCELLED,
                    fill_datetime   = None,
                    fill_price      = None,
                    fill_volume     = 0,
                    direction       = order.direction,
                    offset          = order.offset,
                    commission      = 0.0,
                    session         = order.session,
                    reject_reason   = "cancelled by strategy",
                    tag             = order.tag,
                    client_order_id = order.client_order_id,
                )
        return None

    # ── 撮合：在 bar 到来时调用 ──────────────────────────────────────

    def match_at(self, bar: Bar) -> List[Fill]:
        """
        新 bar 到来时尝试撮合该品种所有 pending 订单。

        市价订单：本 bar 收盘成交（提交发生在上一根 bar 收盘后，在本根 bar 收盘成交）
        限价订单：检查本根 bar 的 [low, high] 是否触达限价；触达则成交，
                  否则计数 +1，若超过 max_wait 则 EXPIRED。

        撮合优先级（price-time priority, 贴近交易所规则）:
            - 限价买单：限价高的先成交（价高更愿意买）
            - 限价卖单：限价低的先成交（价低更愿意卖）
            - 同价同方向：按 submit_ts 早的先成交
            - 市价 / 止损：保持提交先后顺序（无价格优先意义）
        """
        pending_list = self._pending.get(bar.symbol, [])
        if not pending_list:
            return []

        ordered = self._sort_by_price_time(pending_list)

        fills: List[Fill] = []
        remaining: List[_PendingOrder] = []
        for po in ordered:
            order = po.order
            if order.order_type == ORDER_MARKET_0905:
                if bar.timestamp.hour == 9 and bar.timestamp.minute == 5:
                    fills.append(self._fill_at_price(order, bar.timestamp, bar.open))
                else:
                    fills.append(self._expired(order, "下一交易日缺少 09:05 行情"))
                continue
            if order.order_type in (ORDER_MARKET, ORDER_STOP):
                fills.append(self._fill_at_price(order, bar.timestamp, bar.close))
                continue

            if order.order_type == ORDER_LIMIT:
                if order.price is None:
                    fills.append(self._reject(order, "limit 单缺 price"))
                    continue
                touched, fill_price = self._limit_touched(order, bar)
                if touched:
                    fills.append(self._fill_at_price(order, bar.timestamp, fill_price))
                else:
                    po.bars_waited += 1
                    if po.bars_waited >= self._max_wait:
                        fills.append(self._expired(order))
                    else:
                        remaining.append(po)
                continue

            fills.append(self._reject(order, f"未知 order_type: {order.order_type}"))

        self._pending[bar.symbol] = remaining
        return fills

    @staticmethod
    def _sort_by_price_time(pending_list: List[_PendingOrder]) -> List[_PendingOrder]:
        """按 price-time priority 排序：限价单价格优先，同价按提交时间。

        市价 / 止损单无价格意义，保持原相对顺序（稳定排序保证）。
        买卖单分桶后各自排序，避免互相干扰；最后按"先卖后买"合并（顺序对最终
        Fill 列表只是顺序差，无逻辑影响；为确定性选一种）。
        """
        bids: List[tuple] = []   # 买（direction == 1）
        asks: List[tuple] = []   # 卖（direction == -1）
        others: List[tuple] = []
        for idx, po in enumerate(pending_list):
            o = po.order
            if o.order_type != ORDER_LIMIT or o.price is None:
                others.append((idx, po))
                continue
            if o.direction == 1:
                bids.append((idx, po))
            else:
                asks.append((idx, po))

        # 买单：限价高的先 → -price 升序；同价按 submit_ts 升序；最后用 idx 保稳
        bids.sort(key=lambda t: (-float(t[1].order.price), t[1].submit_ts, t[0]))
        # 卖单：限价低的先 → price 升序；同价按 submit_ts 升序
        asks.sort(key=lambda t: (float(t[1].order.price), t[1].submit_ts, t[0]))
        # 市价 / 止损：保持原顺序
        # 合并顺序：先 asks → 再 bids → 再 others；只要顺序确定即可
        return [po for _, po in asks] + [po for _, po in bids] + [po for _, po in others]

    def force_close_pending(self, bar: Bar) -> List[Fill]:
        """日终强制以当前 bar close 把所有 pending 限价单撤掉为 EXPIRED。"""
        fills: List[Fill] = []
        for po in self._pending.get(bar.symbol, []):
            fills.append(self._expired(po.order))
        self._pending[bar.symbol] = []
        return fills

    # ── 内部辅助 ──────────────────────────────────────────────────────

    def _fill_at_price(self, order: Order, ts: pd.Timestamp, price: float) -> Fill:
        slipped = self._apply_slippage(order, price)
        commission = 0.0  # 由 accountant 在 trade 配对时计算，避免重复
        return Fill(
            fill_id         = uuid.uuid4().hex[:8],
            order_id        = order.order_id,
            signal_id       = order.signal_id,
            strategy_id     = order.strategy_id,
            symbol          = order.symbol,
            contract        = order.contract,
            status          = FILL_FILLED,
            fill_datetime   = ts,
            fill_price      = float(slipped),
            fill_volume     = int(order.volume),
            direction       = order.direction,
            offset          = order.offset,
            commission      = commission,
            session         = order.session,
            reject_reason   = None,
            tag             = order.tag,
            client_order_id = order.client_order_id,
        )

    def _expired(self, order: Order,
                 reason: str = "limit 超过最大等待 bar 数未成交") -> Fill:
        return Fill(
            fill_id         = uuid.uuid4().hex[:8],
            order_id        = order.order_id,
            signal_id       = order.signal_id,
            strategy_id     = order.strategy_id,
            symbol          = order.symbol,
            contract        = order.contract,
            status          = FILL_EXPIRED,
            fill_datetime   = None,
            fill_price      = None,
            fill_volume     = 0,
            direction       = order.direction,
            offset          = order.offset,
            commission      = 0.0,
            session         = order.session,
            reject_reason   = reason,
            tag             = order.tag,
            client_order_id = order.client_order_id,
        )

    def _reject(self, order: Order, reason: str) -> Fill:
        return Fill(
            fill_id         = uuid.uuid4().hex[:8],
            order_id        = order.order_id,
            signal_id       = order.signal_id,
            strategy_id     = order.strategy_id,
            symbol          = order.symbol,
            contract        = order.contract,
            status          = "rejected",
            fill_datetime   = None,
            fill_price      = None,
            fill_volume     = 0,
            direction       = order.direction,
            offset          = order.offset,
            commission      = 0.0,
            session         = order.session,
            reject_reason   = reason,
            tag             = order.tag,
            client_order_id = order.client_order_id,
        )

    def _apply_slippage(self, order: Order, raw_price: float) -> float:
        ci = self._ci.get(order.symbol, {})
        tick = float(ci.get("tick_size", 1.0))
        slip = float(ci.get("slip", 1.5))
        delta = tick * slip
        # 开仓买/平空买：加价；开仓卖/平多卖：减价
        if order.direction == 1:
            return raw_price + delta
        return raw_price - delta

    def _limit_touched(self, order: Order, bar: Bar) -> tuple[bool, float]:
        """限价单是否在本 bar 触达。"""
        if order.price is None:
            return False, 0.0
        if order.direction == 1:
            # 买入限价：bar.low <= limit 则成交，成交价 = min(open, limit)
            if bar.low <= order.price:
                return True, min(bar.open, order.price)
            return False, 0.0
        # 卖出限价：bar.high >= limit 则成交
        if bar.high >= order.price:
            return True, max(bar.open, order.price)
        return False, 0.0
