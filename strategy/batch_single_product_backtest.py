"""Run all single-product strategies from the first four categories.

Each combination gets its own output prefix:
    <strategy>_<direction>_<timeframe>_all

The runner resumes only successful results with matching run fingerprints.
It intentionally leaves the source strategies and the normal CLI unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from strategies import discover_strategy_catalog


TARGET_CATEGORIES = (
    "趋势跟踪与趋势强度类",
    "突破与通道类",
    "均值回归与震荡反转类",
    "量价资金流类",
)
DIRECTIONS = ("long", "short", "both")
TIMEFRAMES = ("15m", "1h", "1d")


def build_jobs(output_dir: Path) -> list[tuple[str, str, str, str]]:
    packages = [
        item["name"] for item in discover_strategy_catalog()
        if item["category"] in TARGET_CATEGORIES
    ]
    jobs = []
    for package in packages:
        for timeframe in TIMEFRAMES:
            for direction in DIRECTIONS:
                prefix = f"{package}_{direction}_{timeframe}_all"
                result = output_dir / "capital" / f"capital_daily_{prefix}.csv"
                jobs.append((package, direction, timeframe, prefix))
                if result.is_file():
                    continue
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(Path(__file__).resolve().parent.parent / "data" / "future_price"))
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--force", action="store_true", help="重新运行已有结果")
    parser.add_argument("--symbols", nargs="+", default=None, help="留空使用数据目录中的全部品种")
    parser.add_argument("--plan-only", action="store_true", help="只生成可审阅的任务清单")
    parser.add_argument("--plots", action="store_true", help="额外生成逐品种 PNG（批量默认关闭）")
    parser.add_argument("--directions", nargs="+", choices=DIRECTIONS, default=["both"])
    parser.add_argument("--timeframes", nargs="+", choices=TIMEFRAMES, default=["1h", "1d"])
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    output_dir = (root / args.output_dir).resolve()
    log_dir = output_dir / "batch_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    catalog = discover_strategy_catalog()
    packages = [item["name"] for item in catalog if item["category"] in TARGET_CATEGORIES]
    directions = tuple(args.directions)
    timeframes = tuple(args.timeframes)
    digest = hashlib.sha256((root / "SOURCE_MANIFEST.json").read_bytes())
    code_paths = {root/"run_backtest.py", *list((root/"config").glob("*.yaml"))}
    for component in ("strategies", "framework", "core", "data_sources", "performance"):
        code_paths.update((root/component).rglob("*.py"))
    for code_path in sorted(code_paths):
        digest.update(code_path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(code_path.read_bytes())
    source_hash = digest.hexdigest()[:10]
    available_symbols = sorted(p.stem for p in Path(args.data_dir).glob("*.h5"))
    symbols = args.symbols or available_symbols
    if not symbols:
        raise ValueError(f"没有可回测的数据: {args.data_dir}")
    data_versions = {s: (p.stat().st_size, p.stat().st_mtime_ns)
                     for s in symbols if (p := Path(args.data_dir)/(s+".h5")).is_file()}
    job_config = json.dumps(dict(symbols=symbols, data_dir=str(Path(args.data_dir).resolve()),
                                 start=args.start, end=args.end, source=source_hash,
                                 plots=args.plots, volume=1, adapter="passthrough", data_versions=data_versions), sort_keys=True)
    run_hash = hashlib.sha256(job_config.encode()).hexdigest()[:10]
    scope = "all" if sorted(set(symbols)) == available_symbols else "_".join(symbols)
    jobs = [(p, d, t, f"{p}_{d}_{t}_{scope}") for p in packages for t in timeframes for d in directions]
    plan = dict(source_hash=source_hash, batch_fingerprint=run_hash, volume=1, adapter="passthrough",
                symbols=symbols, data_dir=str(Path(args.data_dir).resolve()),
                start=args.start, end=args.end, jobs=[dict(strategy=p, direction=d, timeframe=t, prefix=prefix)
                                                    for p,d,t,prefix in jobs])
    plan_path = output_dir / "runs" / f"batch_matrix_{run_hash}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"任务清单: {plan_path} | 数据品种: {len(symbols)}")
    if args.plan_only:
        return 0

    print(f"批量回测策略数: {len(packages)}")
    print(f"回测任务数: {len(jobs)}")
    print(f"周期: {', '.join(timeframes)} | 方向: {', '.join(directions)} | 每品种固定 1 手")

    completed = skipped = failed = 0
    for index, (package, direction, timeframe, prefix) in enumerate(jobs, 1):
        completion_path = output_dir / "runs" / f"{prefix}.complete.json"
        previous = {}
        if completion_path.is_file():
            try:
                previous = json.loads(completion_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                pass
        if (previous.get("status") == "complete" and previous.get("batch_fingerprint") == run_hash
                and not args.force):
            skipped += 1
            print(f"[{index}/{len(jobs)}] 跳过已有结果: {prefix}")
            continue
        command = [
            sys.executable, "run_backtest.py", "--strategy", package,
            "--timeframe", timeframe, "--direction", direction,
            "--volume", "1", "--adapter", "passthrough",
            "--data-dir", args.data_dir, "--prefix", prefix,
            "--out-dir", str(output_dir), "--symbols", *symbols,
        ]
        if args.start:
            command.extend(["--start", args.start])
        if args.end:
            command.extend(["--end", args.end])
        if not args.plots:
            command.append("--no-plots")
        log_path = log_dir / f"{prefix}.log"
        print(f"[{index}/{len(jobs)}] 开始: {prefix}")
        completion_path.write_text(json.dumps(dict(status="running", batch_fingerprint=run_hash,
                                                   prefix=prefix), indent=2), encoding="utf-8")
        started = datetime.now().isoformat(timespec="seconds")
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"started={started}\ncommand={' '.join(command)}\n\n")
            result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, text=True)
            log.write(f"\nreturncode={result.returncode}\nfinished={datetime.now().isoformat(timespec='seconds')}\n")
        if result.returncode == 0:
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["batch_fingerprint"] = run_hash
            completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8")
            completed += 1
            print(f"[{index}/{len(jobs)}] 完成: {prefix}")
        else:
            failed += 1
            print(f"[{index}/{len(jobs)}] 失败: {prefix}，详见 {log_path}")

    print(f"批量回测结束：完成 {completed}，跳过 {skipped}，失败 {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
