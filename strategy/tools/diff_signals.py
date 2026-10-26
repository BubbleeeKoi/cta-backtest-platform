"""
tools/diff_signals.py  ——  实盘 vs 回测 signals 对账

每日盘后用法
    # 1) 用与实盘同源的数据源跑当日回测
    python strategy/run_backtest.py --strategy all \
        --data-source live_archive \
        --start 2026-05-20 --end 2026-05-20 \
        --prefix verify_20260520

    # 2) 比对实盘当日 signals 和回测产物
    python strategy/tools/diff_signals.py \
        --backtest strategy/output/signals/signals_verify_20260520.csv \
        --live     /path/to/live/signals/signals_20260520.csv \
        --report   strategy/output/verify/diff_20260520.csv

输出三类差异
    BACKTEST_ONLY   回测发了、实盘没发    (实盘漏单 / 行情服务异常)
    LIVE_ONLY       实盘发了、回测没发    (实盘多发 / 数据源不一致)
    ATTR_MISMATCH   主键命中但属性不一致  (price / order_type / session / tag)

匹配键（默认）
    (strategy_id, symbol, action_datetime, bar_datetime,
     signal_kind, direction, offset)

  signal_id（uuid）和 bar_* 上下文不参与匹配；mismatch 时辅助定位是否
  数据源差异（bar_close 不同 → 数据源差异；bar_close 相同 → 策略行为漂移）。

退出码
    0 = 完全一致；1 = 有差异；2 = 输入文件缺失/格式错。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import pandas as pd

# 主键列（参与匹配）
_KEY_COLS: List[str] = [
    "strategy_id", "symbol",
    "action_datetime", "bar_datetime",
    "signal_kind", "direction", "offset",
]

# 属性列（参与一致性校验，但不参与匹配）
_ATTR_COLS: List[str] = [
    "order_type", "price", "volume_hint", "session", "tag",
]

# 上下文列（仅用于 mismatch 时辅助定位）
_CONTEXT_COLS: List[str] = [
    "signal_id",
    "bar_open", "bar_high", "bar_low", "bar_close", "bar_volume", "bar_oi",
]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="实盘 vs 回测 signals 对账",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--backtest", required=True, help="回测 signals CSV 路径")
    p.add_argument("--live",     required=True, help="实盘 signals CSV 路径")
    p.add_argument("--report",   default=None, help="对账报告输出 CSV；缺省时仅打印汇总")
    p.add_argument("--time-grain", default="minute", choices=("second", "minute"),
                   help="time floor 粒度（实盘 action_datetime 通常毫秒级，建议按分钟对齐）")
    p.add_argument("--price-tol", type=float, default=1e-6,
                   help="price 字段比较容差（绝对值）")
    return p.parse_args()


def _load_signals(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        print(f"[ERROR] {label} 文件不存在: {path}")
        sys.exit(2)
    df = pd.read_csv(path)
    missing = [c for c in _KEY_COLS if c not in df.columns]
    if missing:
        print(f"[ERROR] {label} 缺少必需列: {missing}（{path}）")
        sys.exit(2)
    # 时间列统一成 datetime
    for col in ("action_datetime", "bar_datetime"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _normalize_keys(df: pd.DataFrame, time_grain: str) -> pd.DataFrame:
    """按 time_grain floor 时间列，保证两端可对齐。"""
    rule = "1s" if time_grain == "second" else "1min"
    df = df.copy()
    df["action_datetime"] = df["action_datetime"].dt.floor(rule)
    df["bar_datetime"]    = df["bar_datetime"].dt.floor(rule)
    df["direction"] = pd.to_numeric(df["direction"], errors="coerce").astype("Int64")
    return df


def _attrs_equal(a: pd.Series, b: pd.Series, price_tol: float) -> List[str]:
    """返回不一致的属性列名列表（空 = 全一致）。"""
    diffs: List[str] = []
    for col in _ATTR_COLS:
        if col not in a or col not in b:
            continue
        va, vb = a[col], b[col]
        if col == "price":
            try:
                fa = float(va) if pd.notna(va) else None
                fb = float(vb) if pd.notna(vb) else None
            except (TypeError, ValueError):
                fa, fb = va, vb
            if (fa is None) != (fb is None):
                diffs.append(col)
            elif fa is not None and abs(fa - fb) > price_tol:
                diffs.append(col)
        else:
            na, nb = pd.isna(va), pd.isna(vb)
            if na != nb:
                diffs.append(col)
            elif not na and str(va) != str(vb):
                diffs.append(col)
    return diffs


def diff_signals(
    bt: pd.DataFrame, live: pd.DataFrame, price_tol: float,
) -> pd.DataFrame:
    """按主键 outer join；输出 status ∈ {OK, BACKTEST_ONLY, LIVE_ONLY, ATTR_MISMATCH}。"""
    bt = bt.copy(); live = live.copy()
    bt["__src__"] = "bt"
    live["__src__"] = "live"

    # 先各自按主键去重（同一 signal 同时刻不应重复；若重复保留首条并标记）
    bt_dedup = bt.drop_duplicates(_KEY_COLS, keep="first")
    live_dedup = live.drop_duplicates(_KEY_COLS, keep="first")

    merged = bt_dedup.merge(
        live_dedup, on=_KEY_COLS, how="outer",
        suffixes=("_bt", "_live"), indicator=True,
    )

    out_rows = []
    for _, row in merged.iterrows():
        base = {k: row[k] for k in _KEY_COLS}
        ind = row["_merge"]
        if ind == "left_only":
            status = "BACKTEST_ONLY"
            diffs: List[str] = []
        elif ind == "right_only":
            status = "LIVE_ONLY"
            diffs = []
        else:
            # both: 检查属性是否一致
            a = {c: row.get(f"{c}_bt")   for c in _ATTR_COLS + _CONTEXT_COLS}
            b = {c: row.get(f"{c}_live") for c in _ATTR_COLS + _CONTEXT_COLS}
            diffs = _attrs_equal(pd.Series(a), pd.Series(b), price_tol)
            status = "OK" if not diffs else "ATTR_MISMATCH"

        out_rows.append({
            **base,
            "status":      status,
            "mismatched":  ",".join(diffs) if diffs else "",
            # 让排查时能立刻看出 bar_close 是否一致：把两端的 bar_close 同时输出
            "bar_close_bt":   row.get("bar_close_bt"),
            "bar_close_live": row.get("bar_close_live"),
        })

    return pd.DataFrame(out_rows)


def _print_summary(diff_df: pd.DataFrame) -> None:
    total = len(diff_df)
    by_status = diff_df["status"].value_counts().to_dict()
    print()
    print(f"  signals 对账 (total = {total})")
    print(f"  {'─' * 40}")
    for s in ("OK", "BACKTEST_ONLY", "LIVE_ONLY", "ATTR_MISMATCH"):
        n = by_status.get(s, 0)
        flag = "" if s == "OK" else " *"
        print(f"   {s:<16} {n:>6}{flag}")
    print()


def main() -> int:
    args = _parse_args()
    bt   = _load_signals(Path(args.backtest), "backtest")
    live = _load_signals(Path(args.live), "live")

    bt_n   = _normalize_keys(bt, args.time_grain)
    live_n = _normalize_keys(live, args.time_grain)

    diff_df = diff_signals(bt_n, live_n, price_tol=args.price_tol)
    _print_summary(diff_df)

    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        diff_df.to_csv(out, index=False, encoding="utf-8-sig")
        print(f"  详细报告 → {out}")

    bad = diff_df[diff_df["status"] != "OK"]
    return 0 if bad.empty else 1


if __name__ == "__main__":
    sys.exit(main())
