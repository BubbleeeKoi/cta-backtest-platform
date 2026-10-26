"""
framework/  ——  CTA 策略契约层

实盘和回测两端**部署同一份代码**，策略包无需为两种场景写两套实现。

对外暴露:
    Strategy           策略基类（成员继承）
    Bar / Signal / Order / Fill / Position    数据类
    Snapshot           横截面 lazy 视图（on_bar 第二参）
    HistoryView        on_init 预热历史视图
    DataPool           数据池抽象接口（实盘/回测各自实现）
    OrderBook          策略侧未成交订单簿（实盘辅助）
"""
from .action_recorder import ActionRecorder
from .base import Strategy
from .contract_util import (
    clip01,
    commission_per_side,
    infer_symbol_from_contract_info,
    normalize_symbol,
    roundtrip_cost_price,
    tick_size,
)
from .data_pool import BatchDataPool, DataPool
from .order_book import OrderBook
from .signal_recorder import SignalRecorder
from .snapshot import HistoryView, Snapshot
from .types import (
    # 数据类
    Bar,
    Fill,
    Order,
    Position,
    Signal,
    # Signal kind 常量
    SIGNAL_ENTRY,
    SIGNAL_EXIT,
    SIGNAL_STOP_LOSS,
    SIGNAL_TAKE_PROFIT,
    SIGNAL_FORCE_CLOSE,
    # Offset 常量
    OFFSET_OPEN,
    OFFSET_CLOSE,
    OFFSET_CLOSE_TODAY,
    OFFSET_CLOSE_YESTERDAY,
    # Order type 常量
    ORDER_MARKET,
    ORDER_MARKET_0905,
    ORDER_LIMIT,
    ORDER_STOP,
    ORDER_EXACT,
    # Fill status 常量
    FILL_FILLED,
    FILL_PARTIAL,
    FILL_REJECTED,
    FILL_CANCELLED,
    FILL_EXPIRED,
)

__all__ = [
    # 基类
    "Strategy",
    # 数据类
    "Bar",
    "Signal",
    "Order",
    "Fill",
    "Position",
    "Snapshot",
    "HistoryView",
    "DataPool",
    "BatchDataPool",
    "OrderBook",
    "SignalRecorder",
    "ActionRecorder",
    # Signal kind
    "SIGNAL_ENTRY",
    "SIGNAL_EXIT",
    "SIGNAL_STOP_LOSS",
    "SIGNAL_TAKE_PROFIT",
    "SIGNAL_FORCE_CLOSE",
    # Offset
    "OFFSET_OPEN",
    "OFFSET_CLOSE",
    "OFFSET_CLOSE_TODAY",
    "OFFSET_CLOSE_YESTERDAY",
    # Order type
    "ORDER_MARKET",
    "ORDER_MARKET_0905",
    "ORDER_LIMIT",
    "ORDER_STOP",
    "ORDER_EXACT",
    # Fill status
    "FILL_FILLED",
    "FILL_PARTIAL",
    "FILL_REJECTED",
    "FILL_CANCELLED",
    "FILL_EXPIRED",
    # 合约工具
    "normalize_symbol",
    "infer_symbol_from_contract_info",
    "clip01",
    "tick_size",
    "commission_per_side",
    "roundtrip_cost_price",
]
