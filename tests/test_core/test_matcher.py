"""撮合器 Matcher 行为测试。"""
from __future__ import annotations

import pandas as pd

from core.matcher import Matcher
from framework.types import (
    FILL_EXPIRED,
    FILL_FILLED,
    OFFSET_OPEN,
    ORDER_EXACT,
    ORDER_LIMIT,
    ORDER_MARKET,
    Bar,
    Order,
)


def _bar(symbol, ts, o, h, l, c, v=100):
    return Bar(
        symbol=symbol, timestamp=pd.Timestamp(ts),
        tradingday=pd.Timestamp(ts).normalize(),
        open=o, high=h, low=l, close=c, volume=v,
    )


def _order(otype, direction, price=None, vol=2):
    return Order(
        order_id="o1", signal_id="s1", strategy_id="t",
        symbol="RB", contract="RB",
        direction=direction, offset=OFFSET_OPEN,
        order_type=otype, volume=vol, price=price,
        submit_datetime=pd.Timestamp("2024-01-01 09:00"),
        session="早盘盘中", tag="test",
    )


CI = {"RB": {"point": 10, "tick_size": 1.0, "slip": 1.5, "commission_intraday": 5.0, "type": 0.0}}


def test_market_buy_fills_at_close_plus_slippage():
    m = Matcher(CI)
    m.submit_pending([_order(ORDER_MARKET, 1)], pd.Timestamp("2024-01-01 09:00"))
    bar = _bar("RB", "2024-01-01 09:01", o=4000, h=4010, l=3995, c=4005)
    fills = m.match_at(bar)
    assert len(fills) == 1
    f = fills[0]
    assert f.status == FILL_FILLED
    # 买单加价 slip*tick = 1.5
    assert f.fill_price == 4005 + 1.5


def test_market_sell_fills_at_close_minus_slippage():
    m = Matcher(CI)
    m.submit_pending([_order(ORDER_MARKET, -1)], pd.Timestamp("2024-01-01 09:00"))
    bar = _bar("RB", "2024-01-01 09:01", o=4000, h=4010, l=3995, c=4005)
    fills = m.match_at(bar)
    assert fills[0].fill_price == 4005 - 1.5


def test_limit_buy_fills_when_low_touches():
    m = Matcher(CI)
    m.submit_pending([_order(ORDER_LIMIT, 1, price=4000)], pd.Timestamp("2024-01-01 09:00"))
    bar = _bar("RB", "2024-01-01 09:01", o=4002, h=4010, l=3998, c=4005)
    fills = m.match_at(bar)
    assert len(fills) == 1
    assert fills[0].status == FILL_FILLED
    # 限价单：成交价 = min(open, limit) + slippage
    assert fills[0].fill_price == min(4002, 4000) + 1.5


def test_exact_order_fills_immediately_at_specified_price_no_slippage():
    m = Matcher(CI)
    submit_ts = pd.Timestamp("2024-01-01 09:30")
    order = Order(
        order_id="o", signal_id="s", strategy_id="t",
        symbol="RB", contract="RB",
        direction=1, offset=OFFSET_OPEN,
        order_type=ORDER_EXACT, volume=2, price=4123.5,
        submit_datetime=submit_ts,
        session="早盘盘中", tag="exact_test",
    )
    immediate = m.submit_pending([order], submit_ts)
    assert len(immediate) == 1
    f = immediate[0]
    assert f.status == FILL_FILLED
    assert f.fill_price == 4123.5     # 一分一毫不差
    assert f.fill_datetime == submit_ts
    # pending 队列没残留
    assert m._pending.get("RB") in (None, [])


def test_limit_buy_not_touched_expires_after_max_wait():
    m = Matcher(CI, limit_max_wait_bars=2)
    m.submit_pending([_order(ORDER_LIMIT, 1, price=3000)], pd.Timestamp("2024-01-01 09:00"))
    all_fills = []
    # 价格一直没到达
    for i in range(3):
        bar = _bar("RB", f"2024-01-01 09:{i+1:02d}", o=4000, h=4010, l=3995, c=4005)
        all_fills.extend(m.match_at(bar))
    assert any(f.status == FILL_EXPIRED for f in all_fills)
