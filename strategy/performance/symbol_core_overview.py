"""Full-backtest core metrics for each strategy and symbol.

Use the same daily aggregation, metric builder, and Excel formatter as the
performance report's portfolio-level core overview.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def build_symbol_core_overview(
    daily_pnl: pd.DataFrame, trades: pd.DataFrame, config: dict,
) -> pd.DataFrame:
    from src.loader import build_symbol_daily
    from src.reports.core_overview import build as build_core_overview

    trade_columns = ["strategy", "symbol", "profit", "pnl", "commission"]
    trades = trades.reindex(columns=trade_columns)
    rows = []
    for (strategy, symbol), group in daily_pnl.groupby(["strategy", "symbol"], sort=True):
        symbol_daily = build_symbol_daily(group)
        symbol_trades = trades[
            (trades["strategy"] == strategy) & (trades["symbol"] == symbol)
        ]
        overview = build_core_overview(symbol_daily, symbol_trades, config)
        overview.insert(0, "品种", symbol)
        overview.insert(0, "策略", strategy)
        rows.append(overview)

    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def save_symbol_core_overview(
    daily_pnl: pd.DataFrame, trades: pd.DataFrame, config_path: Path,
    output_path: Path,
) -> pd.DataFrame:
    from src.excel_formatter import write_excel
    from src.loader import load_config

    overview = build_symbol_core_overview(daily_pnl, trades, load_config(config_path))
    if overview.empty:
        return overview
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_excel({"品种核心概览": overview}, output_path)
    return overview
