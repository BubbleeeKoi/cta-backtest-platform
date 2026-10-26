"""
tools/compare_runs.py  ——  对比多次回测产出的 portfolio nav

用法:
    python tools/compare_runs.py \
        output/daily/portfolio/daily_pnl_portfolio_passthrough_all.csv \
        output/daily/portfolio/daily_pnl_portfolio_capped_capital_all.csv

输出每个文件的累计净值 / 最大回撤等关键比较项。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", help="多个 portfolio nav csv 文件路径")
    args = p.parse_args()

    rows = []
    for f in args.files:
        path = Path(f)
        if not path.is_file():
            print(f"  [WARN] 文件不存在：{f}")
            continue
        df = pd.read_csv(path)
        if "daily_pnl_pct" not in df.columns:
            print(f"  [WARN] {f} 缺 daily_pnl_pct 列")
            continue
        daily = df.groupby("date")["daily_pnl_pct"].sum() if "date" in df.columns else df["daily_pnl_pct"]
        nav = (1 + daily).cumprod()
        peak = nav.cummax()
        dd = (nav - peak) / peak
        rows.append({
            "file": path.name,
            "n_days": len(daily),
            "total_return_pct": round((nav.iloc[-1] - 1) * 100, 2),
            "max_drawdown_pct": round(dd.min() * 100, 2),
            "ann_sharpe": round(daily.mean() / daily.std() * (252 ** 0.5), 3) if daily.std() > 0 else 0,
        })

    if not rows:
        print("  没有可对比文件")
        return 1
    print("\n  ── 多次回测对比 ──\n")
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
