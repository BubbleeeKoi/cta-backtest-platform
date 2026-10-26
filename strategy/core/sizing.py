"""
core/sizing.py  ——  仓位计算（手数）

PortfolioAdapter 调用 Sizer 决定每个 Order 的手数。
策略不直接接触 Sizer。

当前实现:
    NotionalSizer    固定名义市值法

如需 ATR / 波动率目标等高级算法，继承 BaseSizer 重写 calc_volume()。
"""
from __future__ import annotations


class BaseSizer:
    allocated_capital: float = 0.0

    def calc_volume(self, entry_price: float, point: float) -> int:
        raise NotImplementedError


class NotionalSizer(BaseSizer):
    """
    固定名义市值法。

    volume = max(1, round(allocated_capital / (entry_price * point)))
    """

    def __init__(self, allocated_capital: float):
        self.allocated_capital = float(allocated_capital)

    def calc_volume(self, entry_price: float, point: float) -> int:
        lot_value = entry_price * point
        if lot_value <= 0:
            return 1
        return int(max(1, round(self.allocated_capital / lot_value)))


class FixedLotSizer(BaseSizer):
    """Fixed base lots, independent of capital, price and contract multiplier."""

    def __init__(self, volume: int, allocated_capital: float = 0.0):
        if isinstance(volume, bool) or int(volume) != volume or volume < 1:
            raise ValueError("volume must be a positive integer")
        self.volume = int(volume)
        self.allocated_capital = float(allocated_capital)

    def calc_volume(self, entry_price: float, point: float) -> int:
        return self.volume
