"""
data_sources/  ——  回测可插拔数据源

回测 ``BacktestDataPool`` 不再写死"从哪里读 minute bar"，而是通过本包提供的
``MinuteBarSource`` 抽象注入具体加载器。常用场景：

    hdf5_index    研究回测：商品指数 HDF5（多合约加权指数）
    live_archive  对账回测：实盘行情服务每日落地的 minute bar（与实盘同源）

约定：所有 ``MinuteBarSource.load(symbol)`` 必须返回**统一 schema**——
DataFrame index 为 ``DatetimeIndex(actiontime)``，包含列
``open / high / low / close / volume / oi / tradingday``。
夜盘 bar 的 ``tradingday`` 必须归属次日交易日（与现有 HDF5 口径一致）。
schema 规整由 source 内部完成，调用方零感知。
"""
from .base import MinuteBarSource
from .hdf5_index import HDF5IndexSource
from .hdf5_daily_0905 import HDF5Daily0905Source
from .live_archive import LiveArchiveSource
from .registry import build_source, list_source_types

__all__ = [
    "MinuteBarSource",
    "HDF5IndexSource",
    "HDF5Daily0905Source",
    "LiveArchiveSource",
    "build_source",
    "list_source_types",
]
