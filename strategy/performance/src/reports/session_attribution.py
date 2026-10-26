"""
时段归因表

按 年×月×时段×策略 维度汇总绩效，展示每个策略在每个时段的月度贡献。

输出列：年份、月份、时段、策略、月收益、月胜率(交易日)、
        交易次数、月贡献占比、年初至今收益、月最大回撤、
        最长连续亏损天数、状态
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from src import metrics as M


# ── 状态判定 ────────────────────────────────────────────────

def _session_status(
    monthly_ret: float,
    win_rate: float,
    max_dd: float,
    prev_status: str,
) -> str:
    if max_dd > 0.05 and prev_status == "预警":
        return "严重预警"
    if monthly_ret < 0 and win_rate < 0.45:
        return "预警"
    if monthly_ret <= 0 and win_rate >= 0.4:
        return "观察"
    if monthly_ret > 0 and win_rate >= 0.5:
        return "正常"
    return "观察"


# ── 主函数 ───────────────────────────────────────────────────

def build(
    daily_pnl: pd.DataFrame,
    trades: pd.DataFrame,
    config: dict,
) -> pd.DataFrame:
    """
    时段归因表：每年×月×时段×策略 一行。

    Parameters
    ----------
    daily_pnl : 每日净值表（含 session 字段，由 loader 自动填入）
    trades    : 交易流水表
    config    : config.yaml 加载结果
    """
    df = daily_pnl.copy()
    df["date"]  = pd.to_datetime(df["date"])
    df["year"]  = df["date"].dt.year
    df["month"] = df["date"].dt.month

    tr = trades.copy()
    tr["trade_date"] = pd.to_datetime(tr["trade_date"])
    tr["year"]  = tr["trade_date"].dt.year
    tr["month"] = tr["trade_date"].dt.month

    # 预计算：(year, month, session, strategy) → 交易次数，循环内 O(1) 查找
    tr_cnt = tr.groupby(["year", "month", "session", "strategy"]).size().to_dict()

    rows = []
    prev_status_map: dict[tuple, str] = {}     # (session, strategy) → 状态（跨年连续）
    cum_ret_map: dict[tuple, float] = {}        # (session, strategy, year) → 累计净值（年内）

    for (year, month, session, strategy), grp in df.groupby(
        ["year", "month", "session", "strategy"], sort=True
    ):
        daily_ret = grp["daily_pnl_pct"]
        if daily_ret.empty:
            continue

        monthly_ret = float((1 + daily_ret).prod() - 1)
        net_val = (1 + daily_ret).cumprod()
        win_rate = M.win_rate_by_day(daily_ret)
        max_dd = M.max_drawdown(net_val)
        max_cons_loss = M.max_consecutive_losses(daily_ret)

        # 交易次数（字典查找）
        n_trades = tr_cnt.get((year, month, session, strategy), 0)

        # 年初至今累计收益（每个自然年独立重置）
        key = (session, strategy, year)
        cum_ret_map[key] = cum_ret_map.get(key, 1.0) * (1 + monthly_ret)
        cum_ret = cum_ret_map[key] - 1

        # 状态（跨年连续跟踪，使用 (session, strategy) 作为 key）
        status_key = (session, strategy)
        prev_st = prev_status_map.get(status_key, "正常")
        status = _session_status(monthly_ret, win_rate, max_dd, prev_st)
        prev_status_map[status_key] = status

        rows.append({
            "年份":             year,
            "月份":             month,
            "时段":             session,
            "策略":             strategy,
            "月收益":           monthly_ret,          # 原始值，贡献占比计算用
            "月胜率(交易日)":   f"{win_rate:.2%}" if not np.isnan(win_rate) else "N/A",
            "交易次数":         n_trades,
            "年初至今收益":     f"{cum_ret:.2%}",
            "月最大回撤":       f"{max_dd:.2%}",
            "最长连续亏损天数": max_cons_loss,
            "状态":             status,
        })

    result = pd.DataFrame(rows)

    # 月贡献占比：该策略月收益 / 当月组合总收益
    if not result.empty:
        portfolio_monthly = (
            result.groupby(["年份", "月份"])["月收益"].sum().rename("portfolio_monthly_ret")
        )
        result = result.join(portfolio_monthly, on=["年份", "月份"])
        result["月贡献占比"] = result.apply(
            lambda r: (
                f"{r['月收益'] / r['portfolio_monthly_ret']:.2%}"
                if r["portfolio_monthly_ret"] != 0 else "N/A"
            ),
            axis=1,
        )
        result["月收益"] = result["月收益"].apply(lambda x: f"{x:.2%}")
        result = result.drop(columns=["portfolio_monthly_ret"])

        # 调整列顺序
        cols = [
            "年份", "月份", "时段", "策略", "月收益",
            "月胜率(交易日)", "交易次数", "月贡献占比",
            "年初至今收益", "月最大回撤", "最长连续亏损天数", "状态",
        ]
        result = result[cols]

    return result
