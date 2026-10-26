"""
framework/types.py  ——  契约层数据类

策略只与下面 5 个对象交互：
    Bar       输入：单根 K 线
    Signal    输出：策略意图（不含手数、不含合约）
    Order     框架内部：Adapter 加工后真正下到撮合层的指令（策略不感知）
    Fill      回报：撮合 / 经纪商成交结果
    Position  辅助：持仓状态（框架默认在 on_fill 时自动更新）

这些类的字段在实盘与回测必须完全一致，是策略代码跨端复用的核心契约。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


# ──────────────────────────────────────────────────────────────────────────
# 1. 行情输入
# ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Bar:
    """
    单根 K 线（默认 1 分钟，框架不强制周期）。

    字段:
        symbol      品种代码（产品级，如 "RB"）。回测中即数据文件名 stem。
        contract    实际合约代码（如 "RB2405"）。品种级回测时 = symbol。
        timestamp   该 bar 的归属时刻（actiontime；时区无关）
        tradingday  交易日（夜盘 bar 归属次日交易日）
        open / high / low / close  量价
        volume      成交量
        oi          持仓量（缺失时填 0.0）
    """
    symbol: str
    timestamp: pd.Timestamp
    tradingday: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    oi: float = 0.0
    contract: str = ""  # 默认空 = 品种级回测
    is_daily_close: bool = False  # 日线事件源的全日 OHLCV，非盘中执行行


# ──────────────────────────────────────────────────────────────────────────
# 2. 策略输出
# ──────────────────────────────────────────────────────────────────────────

# Signal 类别常量
SIGNAL_ENTRY        = "entry"          # 开仓
SIGNAL_EXIT         = "exit"           # 主动平仓（普通出场）
SIGNAL_STOP_LOSS    = "stop_loss"      # 止损
SIGNAL_TAKE_PROFIT  = "take_profit"    # 止盈
SIGNAL_FORCE_CLOSE  = "force_close"    # 强平（尾盘 / 风控）

# Offset 常量
OFFSET_OPEN            = "open"
OFFSET_CLOSE           = "close"
OFFSET_CLOSE_TODAY     = "close_today"
OFFSET_CLOSE_YESTERDAY = "close_yesterday"

# Order type 常量
ORDER_MARKET = "market"
ORDER_MARKET_0905 = "market_0905"  # 下一交易日 09:05 分钟开盘价成交
ORDER_LIMIT  = "limit"
ORDER_STOP   = "stop"
ORDER_EXACT  = "exact"    # 立即按指定 price 成交，不滑点、不延迟（批处理策略复现历史成交用）


@dataclass(frozen=True)
class Signal:
    """
    策略输出的下单意图。

    "信号" vs "订单" 的边界：
        Signal  = 策略说"我想做什么"。不含手数、不含合约。
        Order   = Adapter 加工后真正发出去的"做什么 + 多少手 + 哪个合约"。

    字段说明:
        signal_id        框架自动生成的 uuid 短串，用于与 Fill 对账
        strategy_id      策略实例 ID（如 "jerome"），框架自动注入
        symbol           品种代码（产品级）
        action_datetime  信号"产生"的真实时刻（实盘 = now；回测 = on_bar 收到该 bar 的时刻）
        bar_datetime     触发信号的 bar 时间戳
        signal_kind      entry / exit / stop_loss / take_profit / force_close
        direction        +1 多 / -1 空
        offset           open / close / close_today / close_yesterday
        order_type       market / limit / stop
        price            限价单填限价；市价单可填参考价（撮合不强用）
        session          NAV 分组用的时段名（参与 daily_pnl_pct 计算）
        tag              自由文本，进入 trades.csv 的 reason 列
    """
    # ---- 必填动作 ----
    symbol: str
    action_datetime: pd.Timestamp
    bar_datetime: pd.Timestamp
    signal_kind: str
    direction: int
    offset: str
    order_type: str
    session: str
    tag: str = ""

    # ---- 可选 ----
    price: Optional[float] = None

    # 手数预设值：当策略已经知道目标手数时填这里，adapter 会跳过 sizer 直接使用。
    # 典型场景：批处理策略 open + close 必须用同一手数（基于 entry_price），
    # 否则 accountant FIFO 配对会出现残量碎片。
    volume_hint: Optional[int] = None

    # 策略侧订单号（用于撤单 / 业务对账）。必须由 self.new_client_order_id(prefix=...)
    # 获取，而非策略自己拼字符串，以确保全局唯一并符合交易系统规则（CTP OrderRef
    # ≤ 21 字节、纯 ASCII 字母数字）。同一 symbol 下未成交挂单的 client_order_id
    # 必须唯一；重复时 Matcher.submit_pending 会抛 ValueError 中断本 bar（fail-fast）。
    # 不打算撤单的策略可以省略不填（默认 None）。
    client_order_id: Optional[str] = None

    # ---- 框架自动填充（策略不传） ----
    signal_id: str = ""
    strategy_id: str = ""

    # ---- 辅助 ----
    @property
    def is_open(self) -> bool:
        """组合层 cap 判定用：True 表示开仓单（offset=OPEN），False 表示平仓。

        组合层 CappedPositionAdapter 仅对 is_open=True 的 signal 走 cap 检查；
        平仓单永远放行，确保止损 / 止盈在任何持仓状态下都能落地。
        """
        return self.offset == OFFSET_OPEN


# ──────────────────────────────────────────────────────────────────────────
# 3. 框架内部订单
# ──────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Order:
    """
    PortfolioAdapter 加工后下到撮合层的真实指令。

    与 Signal 的差别:
        - 多出 volume（手数，由 Adapter 调用 sizer 决定）
        - 多出 contract（实际成交合约；品种级回测 = symbol；实盘 = 主力合约）
        - 可能被 Adapter 缩放 / 拆分 / 否决
    """
    order_id: str
    signal_id: str
    strategy_id: str

    symbol: str
    contract: str

    direction: int
    offset: str
    order_type: str
    volume: int
    price: Optional[float]

    submit_datetime: pd.Timestamp
    session: str
    tag: str = ""

    # 策略侧订单号（透传自 Signal.client_order_id；用于撤单和业务对账）。
    # 框架内部撮合与账务统一用 order_id；client_order_id 仅供策略业务使用。
    client_order_id: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# 4. 成交回报
# ──────────────────────────────────────────────────────────────────────────

# Fill status 常量
FILL_FILLED    = "filled"      # 全部成交
FILL_PARTIAL   = "partial"     # 部分成交
FILL_REJECTED  = "rejected"    # 被撮合 / 经纪商拒绝
FILL_CANCELLED = "cancelled"   # 已撤单
FILL_EXPIRED   = "expired"     # 限价单超时未成交


@dataclass(frozen=True)
class Fill:
    """
    撮合层 / 经纪商回灌给策略的成交结果。

    策略在 on_fill(fill) 里收到，据此更新内部 position。
    框架默认会在 super().on_fill() 里自动维护 self.position。

    字段:
        fill_id           uuid，框架自动生成
        order_id          关联到 Order
        signal_id         关联到 Signal（策略主要用这个对账）
        strategy_id       策略 ID（实盘多策略复用同一撮合时去重用）
        symbol / contract
        status            filled / partial / rejected / cancelled / expired
        fill_datetime     实际成交时间（rejected 时可能为 None）
        fill_price        成交价（rejected 时为 None）
        fill_volume       实际成交手数（0 表示未成交）
        direction         同 Order
        offset            同 Order
        commission        双边手续费（已计入；rejected 时为 0）
        session           NAV 分组用的时段名（透传自 Order.session / Signal.session）
        reject_reason     失败原因（status != filled 时填写）
        tag               透传 Signal.tag（用于 trades.csv 的 reason）
    """
    fill_id: str
    order_id: str
    signal_id: str
    strategy_id: str

    symbol: str
    contract: str

    status: str
    fill_datetime: Optional[pd.Timestamp]
    fill_price: Optional[float]
    fill_volume: int

    direction: int
    offset: str

    commission: float
    session: str = ""
    reject_reason: Optional[str] = None
    tag: str = ""

    # 策略侧订单号（透传自 Order.client_order_id；策略据此对账并清理本地状态）。
    # FILL_CANCELLED / FILL_EXPIRED / "rejected" 等终态都会带回 client_order_id。
    client_order_id: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────
# 5. 持仓状态（框架辅助类）
# ──────────────────────────────────────────────────────────────────────────

@dataclass
class Position:
    """
    单品种持仓状态。框架默认在 Strategy.on_fill 内自动维护。

    长短双向独立记账（符合期货实际）。
    """
    symbol: str
    long_volume: int = 0
    short_volume: int = 0
    long_avg_price: float = 0.0
    short_avg_price: float = 0.0

    @property
    def net_volume(self) -> int:
        """净持仓手数（多减空）。"""
        return self.long_volume - self.short_volume

    @property
    def is_flat(self) -> bool:
        return self.long_volume == 0 and self.short_volume == 0

    def apply_fill(self, fill: Fill) -> None:
        """根据 Fill 更新持仓（仅 status=filled / partial 时生效）。"""
        if fill.status not in (FILL_FILLED, FILL_PARTIAL):
            return
        if fill.fill_volume <= 0 or fill.fill_price is None:
            return

        if fill.offset == OFFSET_OPEN:
            self._open(fill.direction, fill.fill_volume, fill.fill_price)
        else:  # close / close_today / close_yesterday
            # 平仓的 direction 表示"平掉哪个方向"——按期货语义：
            #   direction = +1 → 买平（平空仓）
            #   direction = -1 → 卖平（平多仓）
            self._close(fill.direction, fill.fill_volume)

    def _open(self, direction: int, volume: int, price: float) -> None:
        if direction == 1:
            new_total = self.long_volume + volume
            if new_total > 0:
                self.long_avg_price = (
                    self.long_avg_price * self.long_volume + price * volume
                ) / new_total
            self.long_volume = new_total
        elif direction == -1:
            new_total = self.short_volume + volume
            if new_total > 0:
                self.short_avg_price = (
                    self.short_avg_price * self.short_volume + price * volume
                ) / new_total
            self.short_volume = new_total

    def _close(self, close_direction: int, volume: int) -> None:
        # close_direction = +1 → 买平空；close_direction = -1 → 卖平多
        if close_direction == 1:
            close_volume = min(self.short_volume, volume)
            self.short_volume -= close_volume
            if self.short_volume == 0:
                self.short_avg_price = 0.0
        elif close_direction == -1:
            close_volume = min(self.long_volume, volume)
            self.long_volume -= close_volume
            if self.long_volume == 0:
                self.long_avg_price = 0.0
