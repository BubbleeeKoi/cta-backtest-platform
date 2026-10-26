"""测试 framework/types.py 中的数据类与 Position 行为。"""
from __future__ import annotations

import pandas as pd

from framework.types import (
    FILL_FILLED,
    OFFSET_CLOSE,
    OFFSET_OPEN,
    Fill,
    Position,
)


def _make_fill(direction, offset, volume, price, status=FILL_FILLED):
    return Fill(
        fill_id="f1", order_id="o1", signal_id="s1", strategy_id="dummy",
        symbol="RB", contract="RB",
        status=status,
        fill_datetime=pd.Timestamp("2024-01-01 09:30"),
        fill_price=price, fill_volume=volume,
        direction=direction, offset=offset,
        commission=0.0,
    )


class TestPosition:
    def test_open_long_then_close(self):
        pos = Position(symbol="RB")
        pos.apply_fill(_make_fill(1, OFFSET_OPEN, 3, 4000.0))
        assert pos.long_volume == 3
        assert pos.long_avg_price == 4000.0
        assert pos.net_volume == 3

        # 卖平多
        pos.apply_fill(_make_fill(-1, OFFSET_CLOSE, 2, 4050.0))
        assert pos.long_volume == 1
        assert pos.net_volume == 1

        pos.apply_fill(_make_fill(-1, OFFSET_CLOSE, 1, 4080.0))
        assert pos.is_flat

    def test_open_long_two_times_avg_price(self):
        pos = Position(symbol="RB")
        pos.apply_fill(_make_fill(1, OFFSET_OPEN, 2, 4000.0))
        pos.apply_fill(_make_fill(1, OFFSET_OPEN, 2, 4100.0))
        assert pos.long_volume == 4
        assert pos.long_avg_price == 4050.0

    def test_short_position(self):
        pos = Position(symbol="RB")
        pos.apply_fill(_make_fill(-1, OFFSET_OPEN, 5, 4500.0))
        assert pos.short_volume == 5
        assert pos.net_volume == -5

        # 买平空
        pos.apply_fill(_make_fill(1, OFFSET_CLOSE, 5, 4400.0))
        assert pos.is_flat
