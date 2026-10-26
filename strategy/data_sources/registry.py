"""
data_sources/registry.py  ——  按 yaml 配置构造 MinuteBarSource

集中所有 ``type`` 字符串到具体类的映射，避免 ``run_backtest.py`` 里散布
``if type == ...`` 分支。新增数据源只需:
    1. 写一个 ``MinuteBarSource`` 子类
    2. 在 ``_BUILDERS`` 里注册
    3. 在 ``config/data_source.yaml`` 的对应 type 块下提供参数
"""
from __future__ import annotations

from typing import Callable, Dict, List

from .base import MinuteBarSource
from .hdf5_index import HDF5IndexSource
from .live_archive import LiveArchiveSource


def _build_hdf5_index(cfg: dict) -> MinuteBarSource:
    data_dir = cfg.get("data_dir")
    if not data_dir:
        raise ValueError("data_source.hdf5_index.data_dir 未配置")
    return HDF5IndexSource(data_dir=str(data_dir))


def _build_live_archive(cfg: dict) -> MinuteBarSource:
    bar_dir = cfg.get("bar_dir")
    if not bar_dir:
        raise ValueError("data_source.live_archive.bar_dir 未配置")
    return LiveArchiveSource(
        bar_dir        = str(bar_dir),
        file_pattern   = str(cfg.get("file_pattern", "{symbol}.parquet")),
        schema_version = str(cfg.get("schema_version", "v1")),
    )


_BUILDERS: Dict[str, Callable[[dict], MinuteBarSource]] = {
    "hdf5_index":   _build_hdf5_index,
    "live_archive": _build_live_archive,
}


def list_source_types() -> List[str]:
    return sorted(_BUILDERS.keys())


def build_source(source_type: str, params: dict | None = None) -> MinuteBarSource:
    """根据 ``type`` 与对应子配置块构造 MinuteBarSource。

    用法（在 run_backtest.py）::

        cfg = load_run_config(...)
        source = build_source(cfg.data_source_type, cfg.data_source_params)
        data_pool = BacktestDataPool(symbols, source=source, ...)
    """
    if source_type not in _BUILDERS:
        raise ValueError(
            f"未知 data_source.type={source_type!r}；可选: {list_source_types()}"
        )
    return _BUILDERS[source_type](params or {})


def register_source(name: str, builder: Callable[[dict], MinuteBarSource]) -> None:
    """运行时注册自定义 source（业务方扩展用）。"""
    _BUILDERS[name] = builder
