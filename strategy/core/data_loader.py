"""HDF5 minute-bar loader and contract/sector metadata helpers."""
from __future__ import annotations

import pickle
from pathlib import Path
from typing import Optional

import h5py
import numpy as np
import pandas as pd

# ── 默认路径 ──
_BASE = Path(__file__).resolve().parent.parent   # → strategy/
DEFAULT_DATA_DIR    = "/Users/jerome/Documents/Jerome/数据文档/商品期货指数数据/data/index"
DEFAULT_FUTURE_LIST = str(_BASE / "data" / "future_list.csv")
DEFAULT_INDUSTRY    = str(_BASE / "data" / "industry_map.csv")

DATA_DIR = DEFAULT_DATA_DIR
FUTURE_LIST_PATH = DEFAULT_FUTURE_LIST


def load_symbol_data(symbol: str, data_dir: str = DEFAULT_DATA_DIR) -> Optional[pd.DataFrame]:
    """
    从 HDF5 加载指定品种的 1 分钟 OHLCV 数据。

    返回 DataFrame:
        index   = actiontime (DatetimeIndex)
        columns = open / high / low / close / volume / oi / barsID / tradingday / actionday
    若文件不存在或品种不在文件内，返回 None。
    """
    h5_path = Path(data_dir) / f"{symbol}.h5"
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
    df.index.name    = "actiontime"
    df["actionday"]  = df.index.normalize()

    df.sort_index(inplace=True)
    return df


def load_future_list(future_list_path: str = DEFAULT_FUTURE_LIST) -> pd.DataFrame:
    """读取合约基础信息表，以 product 为索引。"""
    return pd.read_csv(future_list_path, index_col="product")


def load_industry_map(industry_path: str = DEFAULT_INDUSTRY) -> dict[str, str]:
    """
    读取品种 → 板块映射。

    industry_map.csv 字段:
        product   品种代码
        sector    板块代码（如 black_metals / non_ferrous / agri / chemical / precious / energy）

    返回 dict[product, sector]。文件不存在时回退到 future_list.csv 的 industrySub 列。
    """
    path = Path(industry_path)
    if path.is_file():
        df = pd.read_csv(path)
        return dict(zip(df["product"].astype(str), df["sector"].astype(str)))

    # 兜底：从 future_list.csv 的 industrySub 列读
    fl = load_future_list()
    if "industrySub" in fl.columns:
        return {str(p): str(s) for p, s in fl["industrySub"].dropna().items()}
    return {}


def get_tradeable_symbols(
    future_list_path: str = DEFAULT_FUTURE_LIST,
    data_dir: str = DEFAULT_DATA_DIR,
) -> list[str]:
    """返回 future_list 中 trade=True 且本地有 .h5 文件的品种。"""
    fl = load_future_list(future_list_path)
    tradeable = fl[fl["trade"] == True].index.tolist()  # noqa: E712
    data_path = Path(data_dir)
    return [s for s in tradeable if (data_path / f"{s}.h5").exists()]


def symbol_from_contract_info(contract_info) -> Optional[str]:
    """
    从合约元信息中提取品种代码（大写）。

    薄包装：底层规则由 ``framework.contract_util.infer_symbol_from_contract_info``
    统一定义。本函数把空字符串结果规整为 ``None``，方便调用方用
    ``if symbol_from_contract_info(...) is None`` 做缺失判定。
    """
    from framework.contract_util import infer_symbol_from_contract_info
    sym = infer_symbol_from_contract_info(contract_info)
    return sym if sym else None
