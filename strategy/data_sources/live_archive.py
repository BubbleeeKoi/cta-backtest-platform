"""
data_sources/live_archive.py  ——  实盘行情归档数据源（骨架）

用途
    用于"对账回测"：每天盘后用与实盘完全同源的 minute bar 重跑当日回测，
    将产出的 signals.csv 与实盘 signals.csv 做 diff，验证实盘是否按既定
    策略发出了信号。

为什么单独一个 source 类
    - 实盘行情服务推送给我们的 bar，落地形态可能是 parquet / csv / 自研
      binary；schema 与 HDF5 商品指数有差异（如主力合约 vs 指数、夜盘
      归属规则、缺 oi 等）。
    - 把这些差异都关在本文件内做规整，对上层 ``BacktestDataPool`` 透明。

骨架说明
    本文件给出"目录结构 + 加载入口"的骨架，由 IT 在接入实盘行情服务时
    填充 ``_load_one_symbol`` 的实际读取逻辑。一旦实现，上层零改动即可
    通过 ``--data-source live_archive`` 切换运行。

约定 schema（IT 填实现时必须保证）
    返回 DataFrame:
        index   = DatetimeIndex (actiontime, 升序)
        columns = open, high, low, close, volume, oi, tradingday
        tradingday: 夜盘 bar 归属"次日交易日"，与 HDF5 索引口径一致
    缺 oi 时填 0.0，缺 tradingday 时由 source 内部按交易日规则推算。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import pandas as pd

from .base import MinuteBarSource, validate_schema


class LiveArchiveSource(MinuteBarSource):
    """实盘 minute bar 归档加载器（骨架；IT 填充实现）。

    构造:
        source = LiveArchiveSource(
            bar_dir         = "/path/to/live/minute_bars",
            file_pattern    = "{symbol}.parquet",   # 也可改 csv / h5
            schema_version  = "v1",
        )

    期望目录结构（默认；可由 ``file_pattern`` 调整）:
        bar_dir/
            RB.parquet
            CU.parquet
            ...

    每个文件包含该品种"自接入以来"的所有完成 minute bar；实盘 runner 每根
    bar flush 一次追加写入即可。
    """

    def __init__(
        self,
        bar_dir: str,
        file_pattern: str = "{symbol}.parquet",
        schema_version: str = "v1",
    ) -> None:
        self._bar_dir = Path(bar_dir)
        self._file_pattern = file_pattern
        self._schema_version = schema_version

    # ── 协议实现 ──────────────────────────────────────────────────────

    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        path = self._path_for(symbol)
        if not path.is_file():
            return None
        df = self._load_one_symbol(symbol, path)
        if df is None or df.empty:
            return None
        return validate_schema(df, symbol, self.describe())

    def list_available_symbols(self) -> List[str]:
        if not self._bar_dir.is_dir():
            return []
        suffix = self._file_pattern.split(".")[-1]
        return sorted(p.stem for p in self._bar_dir.glob(f"*.{suffix}"))

    def describe(self) -> str:
        return (
            f"LiveArchiveSource(bar_dir={self._bar_dir}, "
            f"pattern={self._file_pattern}, schema_version={self._schema_version})"
        )

    # ── 待 IT 实现 ─────────────────────────────────────────────────────

    def _path_for(self, symbol: str) -> Path:
        return self._bar_dir / self._file_pattern.format(symbol=symbol)

    def _load_one_symbol(self, symbol: str, path: Path) -> Optional[pd.DataFrame]:
        """读取单文件 → 规整到统一 schema。

        默认实现尝试 parquet → csv 两种兜底；实盘接入方可覆盖。
        IT 接入时需要保证:
          1. index 为 actiontime（DatetimeIndex 或可转换的列）
          2. tradingday 跨夜归次日（与 HDF5 索引一致）
          3. 缺 oi 填 0.0；缺 tradingday 由本方法补齐
        """
        suffix = path.suffix.lower()
        try:
            if suffix == ".parquet":
                df = pd.read_parquet(path)
            elif suffix == ".csv":
                df = pd.read_csv(path)
            elif suffix in (".h5", ".hdf5"):
                df = pd.read_hdf(path)
            else:
                raise ValueError(
                    f"[LiveArchiveSource] 未知文件类型 {path.suffix!r}"
                    f"（symbol={symbol}）。IT 可覆盖 _load_one_symbol 自行处理。"
                )
        except Exception as e:
            raise RuntimeError(
                f"[LiveArchiveSource] 读取 {path} 失败: {e}。"
                "schema 未对齐时请覆盖 _load_one_symbol。"
            ) from e

        if "actiontime" in df.columns and not isinstance(df.index, pd.DatetimeIndex):
            df = df.set_index("actiontime")
        df.index = pd.to_datetime(df.index)
        df.index.name = "actiontime"
        return df
