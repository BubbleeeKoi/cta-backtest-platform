"""
core/accounting.py  ——  记账模块

输入: Fill 流（撮合产生）+ contract_info（手续费规则）
输出: trades_df / daily_nav_df

关键设计:
    - 配对：每个 Fill 自动按 (strategy_id, symbol, direction) 排队配对
      open_fill 入栈，close_fill 出栈，FIFO，产生一笔 "trade"
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Tuple

import pandas as pd

from framework.types import (
    FILL_FILLED,
    FILL_PARTIAL,
    OFFSET_OPEN,
    Fill,
)


_TRADE_COLS = [
    "trade_id", "trade_date", "symbol", "strategy", "session",
    "direction", "open_time", "close_time", "open_price", "close_price",
    "volume", "pnl", "commission", "profit", "pnl_pct",
    "holding_minutes", "close_reason",
]

_NAV_COLS = [
    "date", "symbol", "strategy", "session",
    "daily_pnl", "daily_pnl_pct", "commission",
    "num_trades", "win_trades", "net_value",
]


def _resolve_commission(ci: dict) -> Tuple[float, bool]:
    """
    解析手续费规则。

    返回 (rate, is_fixed)
        is_fixed = True  → rate 单位：元/手
        is_fixed = False → rate 单位：成交额比例
    """
    def _valid(v) -> bool:
        if v is None or v == "":
            return False
        try:
            f = float(v)
            return not (math.isnan(f) or f == 0.0)
        except (TypeError, ValueError):
            return False

    v = ci.get("commission_intraday")
    if not _valid(v):
        v = ci.get("commission")
    if not _valid(v):
        v = 5.0
    rate = float(v)

    # 优先看 type 字段
    raw_type = ci.get("type")
    try:
        t = float(raw_type)
        if t == 0.0:
            return rate, True
        if t == 1.0:
            return rate, False
    except (TypeError, ValueError):
        pass

    # 兜底：rate >= 1.0 视为固定元/手
    return rate, rate >= 1.0


@dataclass
class _OpenLeg:
    """已开仓的"腿"，等待平仓配对。"""
    fill: Fill
    remain_volume: int


@dataclass
class _ClosedTrade:
    """配对完成的一笔完整交易。"""
    strategy_id: str
    symbol: str
    session: str
    direction: int
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    open_price: float
    close_price: float
    volume: int
    open_commission: float
    close_commission: float
    tradingday: pd.Timestamp
    open_reason: str
    close_reason: str


class TradeAccountant:
    """
    Fill → trade 配对 + 聚合输出。

    用法:
        acct = TradeAccountant(contract_info_by_symbol, allocated_capital_by_symbol)
        for fill in fills:
            acct.on_fill(fill)
        trades_df = acct.trades_dataframe()
        nav_df    = acct.nav_dataframe(session_names_by_strategy)
    """

    def __init__(
        self,
        contract_info_by_symbol: Dict[str, dict],
        allocated_capital_by_strategy: Dict[str, float],
    ) -> None:
        self._ci = contract_info_by_symbol
        self._cap = allocated_capital_by_strategy
        # 配对栈: (strategy_id, symbol, direction) → FIFO 队列
        self._open_legs: Dict[Tuple[str, str, int], Deque[_OpenLeg]] = {}
        # 完成的 trade 列表
        self._trades: List[_ClosedTrade] = []
        # 逐日盯市所需的真实成交事件，保留开仓、平仓和部分成交。
        self._fills: List[Fill] = []

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    # ── 入口 ──────────────────────────────────────────────────────────

    def on_fill(self, fill: Fill) -> None:
        """收到一笔 fill，配对到已开仓的腿。

        session / signal tag 直接从 fill 上读取（由 matcher 透传自 order）；
        accountant 不再额外缓存这两项元信息。
        """
        if fill.status not in (FILL_FILLED, FILL_PARTIAL) or fill.fill_volume <= 0:
            return
        if fill.fill_price is None or fill.fill_datetime is None:
            return

        self._fills.append(fill)

        key_open = (fill.strategy_id, fill.symbol, fill.direction)
        if fill.offset == OFFSET_OPEN:
            self._open_legs.setdefault(key_open, deque()).append(
                _OpenLeg(fill=fill, remain_volume=fill.fill_volume)
            )
            return

        # close：方向相反 → 找 (strategy, symbol, -direction) 配对
        key_match = (fill.strategy_id, fill.symbol, -fill.direction)
        queue = self._open_legs.get(key_match)
        if not queue:
            # 平了一个没开的仓——可能是策略 bug，但不应崩
            return

        remain = fill.fill_volume
        ci = self._ci.get(fill.symbol, {})
        rate, is_fixed = _resolve_commission(ci)
        point = float(ci.get("point", 10))

        while remain > 0 and queue:
            leg = queue[0]
            paired = min(leg.remain_volume, remain)
            # 计算手续费（单边 × 2 = 双边）
            open_comm  = _calc_comm(rate, is_fixed, leg.fill.fill_price, point, paired)
            close_comm = _calc_comm(rate, is_fixed, fill.fill_price,    point, paired)

            # trade.session 取入场 fill 的 session（由 Order → Fill 透传）；
            # 若入场 fill 未带 session，退化到平仓 fill 的 session。
            trade_session = leg.fill.session or fill.session
            trade = _ClosedTrade(
                strategy_id      = fill.strategy_id,
                symbol           = fill.symbol,
                session          = trade_session,
                direction        = leg.fill.direction,  # 配对的是开仓方向
                open_time        = leg.fill.fill_datetime,  # type: ignore[arg-type]
                close_time       = fill.fill_datetime,
                open_price       = float(leg.fill.fill_price),  # type: ignore[arg-type]
                close_price      = float(fill.fill_price),
                volume           = paired,
                open_commission  = open_comm,
                close_commission = close_comm,
                # 已实现盈亏在平仓成交日确认，不能回填到开仓日。
                tradingday       = pd.Timestamp(fill.fill_datetime).normalize(),
                open_reason      = leg.fill.tag,
                close_reason     = fill.tag,
            )
            self._trades.append(trade)

            leg.remain_volume -= paired
            remain -= paired
            if leg.remain_volume <= 0:
                queue.popleft()

    # ── 输出 ──────────────────────────────────────────────────────────

    def trades_dataframe(self) -> pd.DataFrame:
        """生成 trades.csv 的 DataFrame。"""
        rows = []
        for i, t in enumerate(self._trades):
            ci = self._ci.get(t.symbol, {})
            point = float(ci.get("point", 10))
            pnl_raw = (t.close_price - t.open_price) * t.direction * point * t.volume
            comm = t.open_commission + t.close_commission
            profit = pnl_raw - comm
            cap = self._cap.get(t.strategy_id, 1.0)
            holding = int((t.close_time - t.open_time).total_seconds() / 60)
            rows.append({
                "trade_id":        f"{i:08d}",
                "trade_date":      t.tradingday.date(),
                "symbol":          t.symbol,
                "strategy":        t.strategy_id,
                "session":         t.session,
                "direction":       "long" if t.direction == 1 else "short",
                "open_time":       t.open_time,
                "close_time":      t.close_time,
                "open_price":      round(t.open_price,  4),
                "close_price":     round(t.close_price, 4),
                "volume":          t.volume,
                "pnl":             round(pnl_raw, 2),
                "commission":      round(comm,    2),
                "profit":          round(profit,  2),
                "pnl_pct":         round(profit / cap, 6) if cap > 0 else 0.0,
                "holding_minutes": holding,
                "close_reason":    t.close_reason,
            })
        if not rows:
            return pd.DataFrame(columns=_TRADE_COLS)
        return pd.DataFrame(rows, columns=_TRADE_COLS)

    def nav_dataframe(
        self,
        session_names_by_strategy: Dict[str, List[str]],
        trading_days_by_symbol: Dict[str, List[pd.Timestamp]],
        symbols_by_strategy: Dict[str, List[str]],
    ) -> pd.DataFrame:
        """
        生成 daily_pnl.csv 的 DataFrame。

        每个 (strategy, symbol, session, date) 一行。

        ``trading_days_by_symbol`` 必须为 ``{symbol: 该 symbol 实际有 bar 的
        trading_day 列表}``：未上市/已退市的日子不会写入 NAV 行。

        session 收窄规则：``session_names_by_strategy`` 声明的多个 session 里，
        若整段回测内某个 session 在所有 (symbol, date) 上都 0 笔 trade，则视为
        "策略实际未在该 session 部署"，**不为它写 NAV 行**——避免下游
        组合层 ``mean(daily_pnl_pct)`` 被全 0 session 行 1/N 稀释。

        实现：trades 一次性按 (strategy, symbol, session, trade_date) groupby
        聚合为 dict，再走 (strategy × symbol × session × td) 循环按键查表
        ——把原先 14 万次 DataFrame boolean-mask 扫描压成单次 groupby+dict。
        """
        trades = self.trades_dataframe()

        # 一次性 groupby：key = (strategy, symbol, session, trade_date.date())
        #                value = (sum profit, sum commission, n, n_win)
        agg: Dict[tuple, tuple] = {}
        sessions_with_trades_by_strategy: Dict[str, set] = {}
        if not trades.empty:
            # trade_date 在 trades_dataframe 里已经是 datetime.date 对象（见 _row）
            g = trades.groupby(
                ["strategy", "symbol", "session", "trade_date"], sort=False
            )
            sum_profit = g["profit"].sum()
            sum_comm   = g["commission"].sum()
            cnt        = g.size()
            win_cnt    = g["profit"].apply(lambda s: int((s > 0).sum()))
            for key, total in sum_profit.items():
                agg[key] = (
                    float(total),
                    float(sum_comm.loc[key]),
                    int(cnt.loc[key]),
                    int(win_cnt.loc[key]),
                )
            # 收窄 sessions：仅保留某 strategy 实际产生过 trade 的 sessions
            for strategy, sess in (
                trades[["strategy", "session"]].drop_duplicates().itertuples(index=False)
            ):
                sessions_with_trades_by_strategy.setdefault(strategy, set()).add(sess)

        rows = []
        for strategy, sym_list in symbols_by_strategy.items():
            declared_sessions = session_names_by_strategy.get(strategy) or ["ALL"]
            cap = self._cap.get(strategy, 1.0)
            active_sessions = sessions_with_trades_by_strategy.get(strategy)
            # 实际有 trade 的 session 与声明取交集；都没 trade 时保留声明（避免空表）
            if active_sessions:
                session_names = [s for s in declared_sessions if s in active_sessions] \
                                or list(active_sessions)
            else:
                session_names = list(declared_sessions)

            for sym in sym_list:
                sym_tds = trading_days_by_symbol.get(sym, [])
                for sess in session_names:
                    nav = 1.0
                    for td in sym_tds:
                        td_date = td.date()
                        bucket = agg.get((strategy, sym, sess, td_date))
                        if bucket is None:
                            day_pnl = 0.0
                            day_comm = 0.0
                            n_trades = 0
                            n_win = 0
                        else:
                            day_pnl, day_comm, n_trades, n_win = bucket
                        day_pct = day_pnl / cap if cap > 0 else 0.0
                        nav *= (1.0 + day_pct)
                        rows.append({
                            "date":          td_date,
                            "symbol":        sym,
                            "strategy":      strategy,
                            "session":       sess,
                            "daily_pnl":     round(day_pnl, 2),
                            "daily_pnl_pct": round(day_pct, 8),
                            "commission":    round(day_comm, 2),
                            "num_trades":    n_trades,
                            "win_trades":    n_win,
                            "net_value":     round(nav, 4),
                        })
        if not rows:
            return pd.DataFrame(columns=_NAV_COLS)
        return pd.DataFrame(rows, columns=_NAV_COLS)


def _calc_comm(rate: float, is_fixed: bool, price: float, point: float, volume: int) -> float:
    """单边手续费。"""
    if is_fixed:
        return rate * volume
    return rate * price * point * volume
