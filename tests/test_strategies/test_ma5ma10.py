"""Daily close signals wait for the next trading day's 09:05 event."""

import pandas as pd

from framework import Bar, Fill, FILL_FILLED, OFFSET_CLOSE, OFFSET_OPEN, ORDER_MARKET_0905
from strategies.ma5ma10 import Strategy


def _bar(day: int, hour: int, minute: int, price: float) -> Bar:
    ts = pd.Timestamp("2024-01-02") + pd.Timedelta(days=day, hours=hour, minutes=minute)
    return Bar("RB", ts, ts.normalize(), price, price, price, price, 100)


def _fill(signal, day: int, volume: int) -> Fill:
    return Fill(
        fill_id=f"f{day}", order_id=f"o{day}", signal_id="s",
        strategy_id="ma5ma10", symbol="RB", contract="RB",
        status=FILL_FILLED, fill_datetime=_bar(day, 9, 5, 1).timestamp,
        fill_price=1.0, fill_volume=volume,
        direction=signal.direction, offset=signal.offset,
        commission=0.0, session=signal.session,
        client_order_id=signal.client_order_id,
    )


def test_daily_close_cross_schedules_both_reversal_orders_for_0905():
    strategy = Strategy("ma5ma10", {"product": "RB", "point": 10}, None)
    for day in range(10):
        assert strategy.on_bar(_bar(day, 9, 5, 1000), None) == []
        assert strategy.on_bar(_bar(day, 15, 0, 10), None) == []

    # 09:05 price is execution data, never a daily MA observation.
    assert strategy.on_bar(_bar(10, 9, 5, 1000), None) == []
    opening = strategy.on_bar(_bar(10, 15, 0, 11), None)
    assert len(opening) == 1
    assert opening[0].offset == OFFSET_OPEN
    assert opening[0].direction == 1
    assert opening[0].order_type == ORDER_MARKET_0905

    strategy.on_fill(_fill(opening[0], 11, 3))
    assert strategy.on_bar(_bar(11, 9, 5, 1000), None) == []
    reversal = strategy.on_bar(_bar(11, 15, 0, 1), None)
    assert len(reversal) == 2
    assert [s.offset for s in reversal] == [OFFSET_CLOSE, OFFSET_OPEN]
    assert [s.direction for s in reversal] == [-1, -1]
    assert reversal[0].volume_hint == 3
    assert all(s.order_type == ORDER_MARKET_0905 for s in reversal)

    for signal in reversal:
        strategy.on_fill(_fill(signal, 12, 3))
    assert strategy.position.net_volume == -3


def test_periods_count_daily_close_events():
    strategy = Strategy("ma5ma10", {"product": "RB"}, None,
                        {"fast_period": 2, "slow_period": 3})
    for day in range(3):
        strategy.on_bar(_bar(day, 9, 5, 1000), None)
        assert strategy.on_bar(_bar(day, 15, 0, 10), None) == []
    assert strategy.on_bar(_bar(3, 9, 5, 1000), None) == []
    assert strategy.on_bar(_bar(3, 15, 0, 11), None)[0].direction == 1
