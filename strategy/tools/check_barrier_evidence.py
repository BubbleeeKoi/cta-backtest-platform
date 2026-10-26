"""
tools/check_barrier_evidence.py  ——  接收 trade 端 BarBarrier evidence 并签字

与 trade 端 ``tools/collect_barrier_evidence.py`` 配对使用：

- **trade 端**：每日产出 ``barrier_<date>.csv`` + ``<strategy>_diff_report_<date>.csv``
- **analysis 端（本工具）**：消费这两类 csv，按 analysis 团队的硬性验收口径
  逐项核对，给出红 / 绿灯签字结论。

验收口径
========

**Tier 1（必过；任一 FAIL 拒签）**

1. ``barrier_enabled = True``                     barrier 是否启用
2. ``barrier_timeout_seconds <= 30.0``            等待上限达标
3. ``healthy_ratio >= --min-healthy-ratio``       09:00-09:29 全市场就绪率（默认 0.95）
4. ``contracts_empty = 0``                        无合约 09:30 前完全无 bar
5. S3 diff_report 每行 ``status == 'OK'``         trade stream ↔ analysis batch
   且 ``mismatched`` 为空、``bar_close_bt == bar_close_live``

**Tier 2（健康日必过；timeout 演示日允许 FAIL）**

6. ``barrier_timeout_tds = []``
7. ``barrier_partial_minutes = 0``
8. ``barrier_hit_rate >= 1.0``

CLI
===

::

    # 验收健康日
    python strategy/tools/check_barrier_evidence.py \
        --evidence-csv /path/to/barrier_2026-04-17_S1.csv \
        --diff-report /path/to/<strategy>_diff_report_2026-04-17.csv \
        --evidence-kind healthy

    # 验收 timeout 演示日（仅检查 Tier 1 必过项；Tier 2 允许 FAIL）
    python strategy/tools/check_barrier_evidence.py \
        --evidence-csv /path/to/barrier_2026-04-17_S2.csv \
        --evidence-kind timeout-demo

退出码
======
0 = 验收通过；1 = 任一硬性检查不通过
"""
from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class _Row:
    check: str
    value: str
    expected: str
    status: str
    detail: str


def _read_evidence_csv(path: Path) -> Dict[str, _Row]:
    out: Dict[str, _Row] = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = _Row(
                check=r["check"].strip(),
                value=r.get("value", "").strip(),
                expected=r.get("expected", "").strip(),
                status=r.get("status", "").strip(),
                detail=r.get("detail", "").strip(),
            )
            out[row.check] = row
    return out


def _read_diff_report(path: Path) -> Dict[str, int]:
    counts = {"total": 0, "OK": 0, "BACKTEST_ONLY": 0, "LIVE_ONLY": 0, "ATTR_MISMATCH": 0, "OTHER": 0}
    price_mismatch_rows: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            counts["total"] += 1
            status = (r.get("status") or "").strip().upper()
            if status in counts:
                counts[status] += 1
            else:
                counts["OTHER"] += 1
            bt = r.get("bar_close_bt", "")
            live = r.get("bar_close_live", "")
            if bt and live and bt != live:
                price_mismatch_rows.append(
                    f"{r.get('strategy_id','')}/{r.get('symbol','')}"
                    f" @ {r.get('bar_datetime','')}  bt={bt} live={live}"
                )
    counts["price_mismatch"] = len(price_mismatch_rows)
    counts["_price_mismatch_examples"] = price_mismatch_rows[:5]  # type: ignore[assignment]
    return counts


def _check_evidence(
    rows: Dict[str, _Row],
    kind: str,
    min_healthy_ratio: float,
) -> List[Dict[str, str]]:
    """返回 analysis 端核对结果（每项一条）。

    kind ∈ {'healthy', 'timeout-demo'}
        - healthy: Tier 1 + Tier 2 全检
        - timeout-demo: 仅 Tier 1 必过；Tier 2 允许 FAIL（含 partial / timeout_tds 非空，正是演示意图）
    """
    out: List[Dict[str, str]] = []

    def _add(check: str, ok: bool, observed: str, expected: str, severity: str = "tier1") -> None:
        if severity == "tier1":
            verdict = "PASS" if ok else "FAIL"
        else:
            verdict = "PASS" if ok else ("EXPECTED_FAIL" if kind == "timeout-demo" else "FAIL")
        out.append({
            "check": check,
            "observed": observed,
            "expected": expected,
            "verdict": verdict,
            "severity": severity,
        })

    # Tier 1（任一 FAIL 拒签）
    r = rows.get("barrier_enabled")
    _add("barrier_enabled",
         r is not None and r.value == "True",
         r.value if r else "<missing>",
         "True")

    r = rows.get("barrier_timeout_seconds")
    try:
        val = float(r.value) if r else float("inf")
    except ValueError:
        val = float("inf")
    _add("barrier_timeout_seconds",
         val <= 30.0,
         r.value if r else "<missing>",
         "<=30.0")

    r = rows.get("healthy_ratio")
    try:
        hr = float(r.value) if r else 0.0
    except ValueError:
        hr = 0.0
    _add("healthy_ratio",
         hr >= min_healthy_ratio,
         r.value if r else "<missing>",
         f">={min_healthy_ratio}")

    r = rows.get("contracts_empty")
    try:
        empty_n = int(r.value) if r else -1
    except ValueError:
        empty_n = -1
    _add("contracts_empty",
         empty_n == 0,
         r.value if r else "<missing>",
         "=0")

    # Tier 2（健康日必过；演示日允许 FAIL）
    r = rows.get("barrier_timeout_tds")
    _add("barrier_timeout_tds",
         r is not None and r.value == "[]",
         r.value if r else "<missing>",
         "=[]",
         severity="tier2")

    r = rows.get("barrier_partial_minutes")
    try:
        p = int(r.value) if r else -1
    except ValueError:
        p = -1
    _add("barrier_partial_minutes",
         p == 0,
         r.value if r else "<missing>",
         "=0",
         severity="tier2")

    r = rows.get("barrier_hit_rate")
    try:
        hit = float(r.value) if r else 0.0
    except ValueError:
        hit = 0.0
    _add("barrier_hit_rate",
         hit >= 1.0,
         r.value if r else "<missing>",
         "=1.0",
         severity="tier2")

    return out


def _check_diff(diff_path: Path) -> Dict[str, object]:
    counts = _read_diff_report(diff_path)
    total = counts["total"]
    ok = counts["OK"]
    failed = total - ok
    price_mismatch = counts["price_mismatch"]
    verdict = "PASS" if (failed == 0 and price_mismatch == 0 and total > 0) else "FAIL"
    return {
        "path": str(diff_path),
        "total": total,
        "ok": ok,
        "backtest_only": counts["BACKTEST_ONLY"],
        "live_only": counts["LIVE_ONLY"],
        "attr_mismatch": counts["ATTR_MISMATCH"],
        "other": counts["OTHER"],
        "price_mismatch": price_mismatch,
        "price_mismatch_examples": counts["_price_mismatch_examples"],
        "verdict": verdict,
    }


def _print_evidence_report(
    csv_path: Path,
    kind: str,
    results: List[Dict[str, str]],
) -> bool:
    print()
    print("=" * 78)
    print(f"  Evidence CSV  : {csv_path.name}")
    print(f"  Evidence Kind : {kind}")
    print("=" * 78)
    tier1_fail = False
    tier2_fail_unexpected = False
    print(f"  {'check':<28s} {'observed':<28s} {'expected':<14s} {'verdict':<14s}")
    print("  " + "-" * 76)
    for r in results:
        if r["verdict"] == "FAIL" and r["severity"] == "tier1":
            tier1_fail = True
        if r["verdict"] == "FAIL" and r["severity"] == "tier2":
            tier2_fail_unexpected = True
        print(f"  {r['check']:<28s} {r['observed']:<28s} {r['expected']:<14s} {r['verdict']:<14s}")
    print()
    if tier1_fail:
        print("  ❌ Tier 1 FAIL — 拒签")
    elif tier2_fail_unexpected:
        print("  ❌ Tier 2 FAIL（健康日不应出现 partial / timeout）— 拒签")
    elif kind == "timeout-demo" and not any(r["verdict"] == "EXPECTED_FAIL" for r in results):
        print("  ⚠️  Timeout-demo 模式但未观察到 fallback 触发；样本未生效")
        tier1_fail = True
    else:
        print("  ✅ 通过")
    return not (tier1_fail or tier2_fail_unexpected)


def _print_diff_report(d: Dict[str, object]) -> bool:
    print()
    print("=" * 78)
    print(f"  Diff Report   : {Path(str(d['path'])).name}")
    print("=" * 78)
    print(f"  total           : {d['total']}")
    print(f"  OK              : {d['ok']}")
    print(f"  BACKTEST_ONLY   : {d['backtest_only']}")
    print(f"  LIVE_ONLY       : {d['live_only']}")
    print(f"  ATTR_MISMATCH   : {d['attr_mismatch']}")
    print(f"  OTHER           : {d['other']}")
    print(f"  price_mismatch  : {d['price_mismatch']}（bar_close_bt != bar_close_live）")
    if d["price_mismatch"] > 0 and d["price_mismatch_examples"]:
        for ex in d["price_mismatch_examples"]:  # type: ignore[assignment]
            print(f"      ! {ex}")
    print(f"  verdict         : {d['verdict']}")
    return d["verdict"] == "PASS"


def main() -> int:
    p = argparse.ArgumentParser(description="analysis 端验收 trade BarBarrier evidence")
    p.add_argument(
        "--evidence-csv", action="append", default=[],
        help="trade 端产出的 barrier_<date>.csv（可重复指定多份）",
    )
    p.add_argument(
        "--diff-report", action="append", default=[],
        help="trade 端产出的 <strategy>_diff_report_<date>.csv（可重复）",
    )
    p.add_argument(
        "--evidence-kind", choices=("healthy", "timeout-demo"),
        default="healthy",
        help=(
            "healthy：Tier 1 + Tier 2 全检（partial=0、timeout_tds=[]、hit=1.0）；"
            "timeout-demo：仅 Tier 1 必过、Tier 2 允许故意 FAIL（证 fallback 链路）"
        ),
    )
    p.add_argument(
        "--min-healthy-ratio", type=float, default=0.95,
        help="contracts 09:00-09:29 健康率阈值（默认 0.95，与 trade 端一致）",
    )
    args = p.parse_args()

    if not args.evidence_csv and not args.diff_report:
        print("[ERROR] 至少要给一份 --evidence-csv 或 --diff-report")
        return 1

    all_pass = True

    # 1) evidence csv
    for csv_path_s in args.evidence_csv:
        path = Path(csv_path_s)
        if not path.exists():
            print(f"[ERROR] evidence csv 不存在: {path}")
            all_pass = False
            continue
        rows = _read_evidence_csv(path)
        results = _check_evidence(rows, args.evidence_kind, args.min_healthy_ratio)
        ok = _print_evidence_report(path, args.evidence_kind, results)
        all_pass = all_pass and ok

    # 2) diff report（S3 字段级对账）
    for diff_path_s in args.diff_report:
        path = Path(diff_path_s)
        if not path.exists():
            print(f"[ERROR] diff report 不存在: {path}")
            all_pass = False
            continue
        d = _check_diff(path)
        ok = _print_diff_report(d)
        all_pass = all_pass and ok

    print()
    print("=" * 78)
    print(f"  最终验收  :  {'✅ 通过' if all_pass else '❌ 拒签'}")
    print("=" * 78)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
