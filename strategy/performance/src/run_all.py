"""
一键生成所有绩效报告

用法：
    python src/run_all.py
    python src/run_all.py --trades data/my_trades.csv --daily data/my_daily.csv
    python src/run_all.py --output output/2024Q1

输出：output/ 目录下的 Excel 文件（每张报告一个 Sheet）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 把项目根目录加入 sys.path，使 `src.*` 可直接导入
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd
from src.loader import (
    load_config,
    load_trades,
    load_daily_pnl,
    build_portfolio_daily,
    build_symbol_daily,
)
from src.reports import (
    core_overview,
    annual,
    monthly,
    weekly,
    session_attribution,
)
from src.excel_formatter import write_excel


def run(
    trades_path: Path,
    daily_path: Path,
    output_path: Path,
    config_path: Path,
) -> None:
    print("── 加载配置 ──────────────────────────────────────────")
    config = load_config(config_path)

    print("── 加载数据 ──────────────────────────────────────────")
    trades      = load_trades(trades_path, config)
    daily_pnl   = load_daily_pnl(daily_path, config)

    print(f"   交易流水：{len(trades)} 笔")
    print(f"   每日净值：{len(daily_pnl)} 行")

    portfolio_daily = build_portfolio_daily(daily_pnl)
    symbol_daily    = build_symbol_daily(daily_pnl)

    print("── 计算绩效报告 ───────────────────────────────────────")

    sheets: dict[str, pd.DataFrame] = {}

    print("   [1/7] 核心绩效概览表")
    sheets["核心概览"] = core_overview.build(portfolio_daily, trades, config)

    print("   [2/7] 综合年度绩效表")
    sheets["年度_组合"] = annual.build_portfolio(
        portfolio_daily, symbol_daily, trades, config
    )

    print("   [3/7] 品种年度绩效表")
    sheets["年度_品种"] = annual.build_symbol(symbol_daily, trades, config)

    print("   [4/7] 组合月度绩效表")
    sheets["月度_组合"] = monthly.build_portfolio(portfolio_daily, symbol_daily, trades, config)

    print("   [5/7] 品种月度绩效表")
    sheets["月度_品种"] = monthly.build_symbol(symbol_daily, trades, config)

    print("   [6/7] 组合周度绩效表")
    sheets["周度_组合"] = weekly.build_portfolio(portfolio_daily, symbol_daily, trades, config)

    print("   [7/7] 品种周度绩效表")
    sheets["周度_品种"] = weekly.build_symbol(symbol_daily, trades, config)

    print("   [+] 时段归因表")
    sheets["时段归因"] = session_attribution.build(daily_pnl, trades, config)

    print("── 写出报告 ───────────────────────────────────────────")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_excel(sheets, output_path)
    for sheet_name, df in sheets.items():
        print(f"   Sheet [{sheet_name}] → {len(df)} 行")

    print(f"\n完成！报告已保存至：{output_path}")

def main() -> None:
    parser = argparse.ArgumentParser(description="CTA绩效评价 - 一键生成报告")
    parser.add_argument(
        "--trades", type=Path,
        default=ROOT / "data" / "trades.csv",
        help="交易流水 CSV 路径",
    )
    parser.add_argument(
        "--daily", type=Path,
        default=ROOT / "data" / "daily_pnl.csv",
        help="每日净值 CSV 路径",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "output" / "performance_report.xlsx",
        help="输出 Excel 文件路径",
    )
    parser.add_argument(
        "--config", type=Path,
        default=ROOT / "config.yaml",
        help="配置文件路径",
    )
    args = parser.parse_args()
    run(args.trades, args.daily, args.output, args.config)


if __name__ == "__main__":
    main()
