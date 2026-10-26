"""
数据加载与预处理模块

负责：
- 读取 trades.csv 和 daily_pnl.csv
- 校验字段完整性
- 根据 open_time 自动推算 session
- 提供干净的 DataFrame 供报告模块使用
"""

from __future__ import annotations

import yaml
import pandas as pd
from pathlib import Path
from typing import Optional


# ── 默认路径 ────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
CONFIG_PATH = _ROOT / "config.yaml"
DATA_DIR = _ROOT / "data"


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── 时段推算 ────────────────────────────────────────────────
def _infer_session(open_time: pd.Series, session_rules: list) -> pd.Series:
    """
    根据 open_time 推算 session 标签。
    session_rules 格式：[[start_hhmm, end_hhmm, session_name], ...]
    """
    hhmm = open_time.dt.hour * 100 + open_time.dt.minute
    result = pd.Series("未知时段", index=open_time.index, dtype=str)
    for start, end, name in session_rules:
        mask = (hhmm >= start) & (hhmm < end)
        result[mask] = name
    return result


# ── 交易流水表 ───────────────────────────────────────────────
TRADES_REQUIRED_COLS = {
    "trade_id", "trade_date", "symbol", "strategy",
    "direction", "open_time", "close_time",
    "open_price", "close_price", "volume",
    "pnl", "commission", "profit", "pnl_pct",
    "holding_minutes", "close_reason",
}

def load_trades(
    path: Optional[Path] = None,
    config: Optional[dict] = None,
) -> pd.DataFrame:
    """
    读取交易流水表，自动推算 session，返回标准化 DataFrame。
    """
    path = path or DATA_DIR / "trades.csv"
    config = config or load_config()

    df = pd.read_csv(path, parse_dates=["trade_date", "open_time", "close_time"])

    missing = TRADES_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"trades.csv 缺少必要字段：{missing}")

    # session 由 open_time 自动推算（覆盖原有值）
    df["session"] = _infer_session(df["open_time"], config["session_rules"])

    # 类型规范化
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["volume"] = df["volume"].astype(int)
    df["holding_minutes"] = df["holding_minutes"].astype(int)

    # 衍生字段：是否盈利
    df["is_win"] = df["profit"] > 0

    return df.sort_values("open_time").reset_index(drop=True)


# ── 每日净值表 ───────────────────────────────────────────────
DAILY_PNL_REQUIRED_COLS = {
    "date", "symbol", "strategy", "session",
    "daily_pnl", "daily_pnl_pct", "num_trades",
    "win_trades", "net_value",
}

# 每个品种×策略×时段分配的固定资本（方案A，用于毛收益还原）
ALLOCATED_CAPITAL = 1_000_000


def load_daily_pnl(
    path: Optional[Path] = None,
    config: Optional[dict] = None,
) -> pd.DataFrame:
    """
    读取每日净值表，校验字段，返回标准化 DataFrame。
    commission 列可选：若存在则使用，否则填0（向后兼容旧数据）。
    """
    path = path or DATA_DIR / "daily_pnl.csv"
    config = config or load_config()

    df = pd.read_csv(path, parse_dates=["date"])

    missing = DAILY_PNL_REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"daily_pnl.csv 缺少必要字段：{missing}")

    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["num_trades"] = df["num_trades"].astype(int)
    df["win_trades"] = df["win_trades"].astype(int)

    # commission 列：若缺失则补0
    if "commission" not in df.columns:
        df["commission"] = 0.0
    df["commission"] = df["commission"].fillna(0.0).astype(float)

    return df.sort_values("date").reset_index(drop=True)


# ── 组合日收益（按品种等权聚合）─────────────────────────────────
def build_portfolio_daily(daily_pnl: pd.DataFrame) -> pd.DataFrame:
    """
    从每日净值表聚合出组合层面的日收益序列（V0.3 口径）。

    业务语义：**每品种 1 个 ALLOCATED_CAPITAL（默认 100 万）资金池**，多策略
    /多 session 共享同品种资金池；max_stack 控制并发持仓上限，可达 max_stack
    倍杠杆（符合期货保证金交易实践）。

    计算链路（与 2026_04_17_CTA_V0.3 / run_portfolio._build_symbol_nav 等价）：

        1. 先按 ``(date, symbol)`` 把多策略/多 session 的 daily_pnl 全部 sum，
           等价于把同品种当日所有 slot 合并；
        2. ``daily_pnl_pct(symbol) = sum(daily_pnl) / ALLOCATED_CAPITAL``；
        3. 组合 ``daily_pnl_pct = mean(daily_pnl_pct(symbol)) over symbols``
           ≡ ``sum(daily_pnl) / (n_symbols × ALLOCATED_CAPITAL)``；
        4. ``net_value = cumprod(1 + daily_pnl_pct)``。

    返回列：date, daily_pnl_pct, gross_daily_pnl_pct, daily_pnl,
            daily_commission, num_trades, win_trades, net_value
    """
    df = daily_pnl.copy()

    # 先按 (date, symbol) 合并多策略 / 多 session
    by_sym = (
        df.groupby(["date", "symbol"], as_index=False)
        .agg(
            daily_pnl        = ("daily_pnl",  "sum"),
            daily_commission = ("commission", "sum"),
            num_trades       = ("num_trades", "sum"),
            win_trades       = ("win_trades", "sum"),
        )
    )
    by_sym["daily_pnl_pct"]       = by_sym["daily_pnl"] / ALLOCATED_CAPITAL
    by_sym["gross_daily_pnl_pct"] = (by_sym["daily_pnl"] + by_sym["daily_commission"]) / ALLOCATED_CAPITAL

    # 再按 date 跨品种等权 mean
    grp = (
        by_sym.groupby("date", as_index=False)
        .agg(
            daily_pnl_pct       = ("daily_pnl_pct",       "mean"),
            gross_daily_pnl_pct = ("gross_daily_pnl_pct", "mean"),
            daily_pnl           = ("daily_pnl",           "sum"),
            daily_commission    = ("daily_commission",    "sum"),
            num_trades          = ("num_trades",          "sum"),
            win_trades          = ("win_trades",          "sum"),
        )
        .sort_values("date")
    )
    grp["net_value"] = (1 + grp["daily_pnl_pct"]).cumprod()
    return grp.reset_index(drop=True)


def build_symbol_daily(daily_pnl: pd.DataFrame) -> pd.DataFrame:
    """
    从每日净值表聚合出每个品种层面的日收益序列（V0.3 口径）。
    合并同一品种下的所有 strategy×session，分母固定为 ALLOCATED_CAPITAL。

    返回列：date, symbol, daily_pnl_pct, gross_daily_pnl_pct,
            daily_pnl, daily_commission, num_trades, win_trades, net_value
    """
    df = daily_pnl.copy()

    grp = (
        df.groupby(["date", "symbol"], as_index=False)
        .agg(
            daily_pnl        = ("daily_pnl",  "sum"),
            daily_commission = ("commission", "sum"),
            num_trades       = ("num_trades", "sum"),
            win_trades       = ("win_trades", "sum"),
        )
        .sort_values(["symbol", "date"])
    )
    grp["daily_pnl_pct"]       = grp["daily_pnl"] / ALLOCATED_CAPITAL
    grp["gross_daily_pnl_pct"] = (grp["daily_pnl"] + grp["daily_commission"]) / ALLOCATED_CAPITAL
    grp["net_value"] = grp.groupby("symbol")["daily_pnl_pct"].transform(
        lambda s: (1 + s).cumprod()
    )
    return grp.reset_index(drop=True)
