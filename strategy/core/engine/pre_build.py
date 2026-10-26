"""
core/engine/pre_build.py  ——  策略并行预算（batch prebuild）

策略类通过 ``SUPPORTS_BATCH_PREBUILD = True`` 显式声明支持批量预算；并需实现:
    - ``batch_prebuild_args(self) -> dict``    返回可序列化的预算参数
    - ``run_batch_prebuild(cls, args) -> dict`` classmethod，子进程内调用
    - ``set_prebuilt_signals(self, signals)``   注入子进程预算结果

当 ≥2 个 slot 同时声明 SUPPORTS_BATCH_PREBUILD 时，本模块用 ``mp.get_context("spawn")``
并行预算各品种信号，并通过 ``set_prebuilt_signals`` 注入回各 strategy 实例。
"""
from __future__ import annotations

import multiprocessing as mp
import os
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm


def _spawn_prebuild_worker(args: Tuple[str, dict]) -> Tuple[str, Optional[Any]]:
    """Spawn 子进程工作函数。

    args = (task_key, prebuild_args)
    prebuild_args 必须包含 ``run_module`` / ``run_class``，
    指向有 ``run_batch_prebuild(args)`` classmethod 的策略类。
    """
    task_key, prebuild_args = args
    try:
        import importlib
        mod = importlib.import_module(prebuild_args["run_module"])
        cls = getattr(mod, prebuild_args["run_class"])
        signals = cls.run_batch_prebuild(prebuild_args)
        return task_key, signals
    except Exception:
        return task_key, None


def collect_prebuild_capable(slots) -> list:
    """筛选出显式声明 SUPPORTS_BATCH_PREBUILD = True 的 slot。"""
    return [
        s for s in slots
        if getattr(type(s.instance), "SUPPORTS_BATCH_PREBUILD", False)
    ]


def run_parallel_prebuild(slots, n_workers: Optional[int] = None) -> Dict[str, Any]:
    """并行预算并通过 ``Strategy.set_prebuilt_signals`` 注入回各 slot 实例。

    返回 ``{task_key: signals_or_None}``，供调用方做日志/审计；副作用是调用
    ``slot.instance.set_prebuilt_signals(...)``。

    任务以 ``"{strategy_id}__{symbol}"`` 为唯一 key，确保多品种共享 strategy_id
    时仍能正确反查 slot。
    """
    capable = collect_prebuild_capable(slots)
    if len(capable) <= 1:
        return {}

    tasks: List[Tuple[str, dict]] = []
    for slot in capable:
        pb_args = slot.instance.batch_prebuild_args()
        if pb_args is not None:
            task_key = f"{slot.strategy_id}__{slot.symbol}"
            tasks.append((task_key, pb_args))
    if not tasks:
        return {}

    if n_workers is None:
        n_workers = min(len(tasks), os.cpu_count() or 4)

    tqdm.write(f"  并行预算批量信号（{len(tasks)} 品种, {n_workers} workers）...")
    ctx = mp.get_context("spawn")
    with ctx.Pool(n_workers) as pool:
        results = list(
            tqdm(
                pool.imap_unordered(_spawn_prebuild_worker, tasks),
                total=len(tasks),
                desc="预热策略 (batch parallel)",
                ncols=80,
            )
        )

    key_to_slot = {f"{s.strategy_id}__{s.symbol}": s for s in slots}
    out: Dict[str, Any] = {}
    for task_key, batch_sigs in results:
        out[task_key] = batch_sigs
        s = key_to_slot.get(task_key)
        if s is not None and batch_sigs is not None:
            s.instance.set_prebuilt_signals(batch_sigs)
    return out
