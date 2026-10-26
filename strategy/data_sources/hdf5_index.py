"""
data_sources/hdf5_index.py  ——  商品指数 HDF5 数据源

研究回测使用。每个品种一个 ``{SYMBOL}.h5`` 文件，内部按 pandas HDFStore
约定布局（axis1 = actiontime；block0/1/2 = OHLCV+oi+tradingday）。

本文件是从原 ``core/data_loader.py:load_symbol_data`` 平移而来，对外行为
完全一致；现在包装成 ``MinuteBarSource`` 子类，便于和 ``LiveArchiveSource``
等其它数据源并列接入。
"""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import List, Optional

import h5py
import numpy as np
import pandas as pd

from .base import MinuteBarSource, validate_schema


class HDF5IndexSource(MinuteBarSource):
    """从商品指数 HDF5 目录加载 minute bar。

    构造:
        source = HDF5IndexSource(data_dir="/path/to/index/h5/dir")

    目录结构:
        data_dir/
            RB.h5
            CU.h5
            ...
    """

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)

    # ── 协议实现 ──────────────────────────────────────────────────────

    def load(self, symbol: str) -> Optional[pd.DataFrame]:
        h5_path = self._data_dir / f"{symbol}.h5"
        if not h5_path.exists():
            return None

        with h5py.File(h5_path, "r") as f:
            if symbol not in f:
                return None
            grp = f[symbol]

            timestamps = pd.to_datetime(grp["axis1"][:])

            b0_vals = grp["block0_values"][:]
            b0_cols = [x.decode() for x in grp["block0_items"][:]]

            b1_vals = grp["block1_values"][:]
            b1_cols = [x.decode() for x in grp["block1_items"][:]]

            raw_b2 = grp["block2_values"][0]
            td_raw = pickle.loads(bytes(raw_b2)).flatten()

        df = pd.DataFrame(b0_vals, index=timestamps, columns=b0_cols)
        for i, col in enumerate(b1_cols):
            df[col] = b1_vals[:, i]

        td_str = [(x[0] if isinstance(x, (list, np.ndarray)) else x) for x in td_raw]
        df["tradingday"] = pd.to_datetime(td_str, format="%Y%m%d")
        df.index.name = "actiontime"
        df["actionday"] = df.index.normalize()

        df.sort_index(inplace=True)
        return validate_schema(df, symbol, self.describe())

    def list_available_symbols(self) -> List[str]:
        if not self._data_dir.is_dir():
            return []
        return sorted(p.stem for p in self._data_dir.glob("*.h5"))

    def describe(self) -> str:
        return f"HDF5IndexSource({self._data_dir})"
