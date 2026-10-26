"""Event selection, exact 09:05 execution, and realized PnL date."""

import pandas as pd

from core.accounting import TradeAccountant
from core.matcher import Matcher
from data_sources.hdf5_daily_0905 import _event_positions
from framework import (
    Bar, FILL_EXPIRED, FILL_FILLED, OFFSET_CLOSE, OFFSET_OPEN,
    ORDER_MARKET_0905, Order,
)


def _bar(ts: str, open_price: float, close_price: float) -> Bar:
    stamp = pd.Timestamp(ts)
    return Bar("RB", stamp, stamp.normalize(), open_price, open_price,
               close_price, close_price, 100)


def _order(offset=OFFSET_OPEN, direction=1) -> Order:
    return Order(
        order_id="o", signal_id="s", strategy_id="ma5ma10",
        symbol="RB", contract="RB", direction=direction, offset=offset,
        order_type=ORDER_MARKET_0905, volume=2, price=None,
        submit_datetime=pd.Timestamp("2024-01-02 15:00"), session="全天",
    )


def test_only_0905_and_daily_close_events_are_selected():
    timestamps = pd.to_datetime([
        "2024-01-02 09:05", "2024-01-02 15:00",
        "2024-01-02 21:00", "2024-01-03 09:05", "2024-01-03 15:00",
    ])
    tradingdays = pd.to_datetime([
        "2024-01-02", "2024-01-02", "2024-01-03", "2024-01-03", "2024-01-03",
    ])
    assert _event_positions(timestamps, tradingdays).tolist() == [0, 1, 3, 4]


def test_0905_uses_open_price_with_slippage_and_missed_bar_expires():
    ci = {"RB": {"point": 10, "tick_size": 1, "slip": 1.5}}
    matcher = Matcher(ci)
    matcher.submit_pending([_order()], pd.Timestamp("2024-01-02 15:00"))
    fills = matcher.match_at(_bar("2024-01-03 09:05", 100, 110))
    assert len(fills) == 1 and fills[0].status == FILL_FILLED
    assert fills[0].fill_price == 101.5
    assert fills[0].fill_datetime == pd.Timestamp("2024-01-03 09:05")

    matcher.submit_pending([_order()], pd.Timestamp("2024-01-03 15:00"))
    expired = matcher.match_at(_bar("2024-01-04 15:00", 100, 110))
    assert len(expired) == 1 and expired[0].status == FILL_EXPIRED


def test_closed_trade_profit_belongs_to_close_date():
    ci = {"RB": {"point": 10, "tick_size": 1, "slip": 0, "commission": 2, "type": 0}}
    accountant = TradeAccountant(ci, {"ma5ma10": 1_000_000})
    matcher = Matcher(ci)
    matcher.submit_pending([_order()], pd.Timestamp("2024-01-02 15:00"))
    accountant.on_fill(matcher.match_at(_bar("2024-01-03 09:05", 100, 100))[0])
    matcher.submit_pending([_order(OFFSET_CLOSE, -1)], pd.Timestamp("2024-01-03 15:00"))
    accountant.on_fill(matcher.match_at(_bar("2024-01-04 09:05", 110, 110))[0])
    trade = accountant.trades_dataframe().iloc[0]
    assert trade.trade_date == pd.Timestamp("2024-01-04").date()
    assert trade.profit == 192
