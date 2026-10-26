"""
core/config_loader.py  ——  组装 6 个 yaml + CLI 覆盖

按顺序加载:
    config/strategies.yaml    哪些策略 enabled
    config/capital.yaml       资金分配 + adapter 规则
    config/universe.yaml      品种/合约 + 清单
    config/date_range.yaml    回测时段
    config/output.yaml        输出目录
    config/data_source.yaml   数据源路径

然后用 CLI args 做最终覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import yaml

_BASE = Path(__file__).resolve().parent.parent  # → strategy/
DEFAULT_CONFIG_DIR = _BASE / "config"


@dataclass
class RunConfig:
    """归并后的运行配置（CLI + 6 yaml 合并结果）。"""

    # 策略
    enabled_strategies: List[Dict[str, Any]] = field(default_factory=list)
    # 资金 / adapter
    adapter_type: str = "passthrough"
    adapter_params: Dict[str, Any] = field(default_factory=dict)
    per_strategy_capital: float = 1_000_000
    # 品种
    universe_level: str = "product"
    universe_items: List[str] = field(default_factory=list)
    # 时间
    start: Optional[pd.Timestamp] = None
    end:   Optional[pd.Timestamp] = None
    warmup_bars: int = 500
    # 输出
    output_dir: str = "output"
    output_prefix: str = ""
    # 数据源
    data_dir: str = ""                                # 兼容字段：等价于 data_source.hdf5_index.data_dir
    data_source_type: str = "hdf5_index"              # hdf5_index | live_archive
    data_source_params: Dict[str, Any] = field(default_factory=dict)
    future_list_path: str = ""
    industry_map_path: str = ""


def _load_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_run_config(
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    cli_overrides: Optional[dict] = None,
) -> RunConfig:
    """
    从 config_dir 读取 6 个 yaml，叠加 CLI 覆盖，返回 RunConfig。

    cli_overrides 支持的键（与 CLI argparse 对齐）:
        strategy        : str 或 list[str]，"all" / "jerome" / ["jerome", ...]
        adapter         : str
        symbols         : list[str]
        level           : str
        start, end      : str
        timeframe       : 所选策略的 K 线周期（15m / 1h / 1d）
        direction       : 所选策略的方向（long / short / both）
        data_dir        : str
        prefix          : str
        warmup_bars     : int
    """
    cfg_dir = Path(config_dir)
    overrides = cli_overrides or {}

    strategies = _load_yaml(cfg_dir / "strategies.yaml").get("strategies", [])
    cap_yaml   = _load_yaml(cfg_dir / "capital.yaml")
    adapter_cfg= cap_yaml.get("adapter", {})
    universe   = _load_yaml(cfg_dir / "universe.yaml")
    date_range = _load_yaml(cfg_dir / "date_range.yaml").get("date_range", {})
    output     = _load_yaml(cfg_dir / "output.yaml").get("output", {})
    data_src   = _load_yaml(cfg_dir / "data_source.yaml")

    # ── CLI 覆盖策略列表 ──
    sel = overrides.get("strategy")
    if sel and sel != "all":
        if isinstance(sel, str):
            sel = [sel]
        # 只保留选中的；如果选中的策略未在 strategies.yaml 列出，则补一条 enabled=True 的占位项
        listed = {s.get("package"): s for s in strategies}
        new_list = []
        for pkg in sel:
            if pkg in listed:
                entry = dict(listed[pkg])
                entry["enabled"] = True
                new_list.append(entry)
            else:
                new_list.append({"package": pkg, "enabled": True, "weight": 1.0,
                                 "capital": cap_yaml.get("per_strategy_capital", 1_000_000)})
        # 其它策略全部禁用（不出现在 new_list）
        strategies = new_list
    elif sel == "all":
        # 全部 enabled = True
        for s in strategies:
            s["enabled"] = True

    # ── 通用策略参数覆盖 ──
    # timeframe / direction 传给所有选中的策略，策略可以读取并据此
    # 聚合 K 线、限制开仓方向。这样新增策略不需要重新设计 Web 参数名。
    if overrides.get("timeframe") or overrides.get("direction") or overrides.get("volume") is not None:
        for strategy_cfg in strategies:
            params = dict(strategy_cfg.get("params") or {})
            if overrides.get("timeframe"):
                params["timeframe"] = overrides["timeframe"]
            if overrides.get("direction"):
                params["direction"] = overrides["direction"]
            if overrides.get("volume") is not None:
                params["volume"] = overrides["volume"]
            strategy_cfg["params"] = params

    enabled = [s for s in strategies if s.get("enabled", True)]

    # ── adapter 覆盖 ──
    adapter_type = overrides.get("adapter") or adapter_cfg.get("type", "passthrough")

    # ── universe 覆盖 ──
    uni_level = overrides.get("level") or universe.get("level", "product")
    uni_items = list(overrides.get("symbols") or universe.get("items", []))

    # ── time ──
    start = overrides.get("start") or date_range.get("start") or None
    end   = overrides.get("end")   or date_range.get("end")   or None
    warmup = overrides.get("warmup_bars") or date_range.get("warmup_bars", 500)

    # ── output ──
    out_dir = overrides.get("out_dir") or output.get("dir", "output")
    out_prefix = overrides.get("prefix") or output.get("prefix", "")
    if not out_prefix:
        if sel and sel != "all" and isinstance(sel, list) and len(sel) == 1:
            out_prefix = sel[0]
        elif sel == "all":
            out_prefix = f"{adapter_type}_all"
        else:
            out_prefix = adapter_type

    # ── data source ──
    # 优先解析新版结构 data_source.{type, <type>: {...}}；不存在则回退到旧版
    # 顶层 ``data_dir:`` 字段，自动按 hdf5_index 处理。CLI ``--data-dir`` 仍仅
    # 影响 hdf5_index 子配置（与历史行为一致），不会跨数据源类型生效。
    ds_section = data_src.get("data_source") if isinstance(data_src.get("data_source"), dict) else None
    cli_ds_type = overrides.get("data_source")
    if ds_section:
        ds_type = (cli_ds_type or ds_section.get("type") or "hdf5_index").lower()
        ds_params = dict(ds_section.get(ds_type) or {})
    else:
        ds_type = (cli_ds_type or "hdf5_index").lower()
        ds_params = {}

    legacy_data_dir = data_src.get("data_dir", "")  # 兼容旧 yaml 顶层 data_dir
    cli_data_dir = overrides.get("data_dir")
    if ds_type == "hdf5_index":
        ds_params.setdefault("data_dir", legacy_data_dir)
        if cli_data_dir:
            ds_params["data_dir"] = cli_data_dir
        effective_data_dir = ds_params.get("data_dir", "") or legacy_data_dir
        if effective_data_dir and not Path(effective_data_dir).is_absolute():
            effective_data_dir = str((Path(effective_data_dir) if cli_data_dir
                                      else _BASE / effective_data_dir).resolve())
            ds_params["data_dir"] = effective_data_dir
    else:
        # 非 hdf5_index 时 CLI --data-dir 不可跨类型生效，避免歧义；
        # 仍把它落到 RunConfig.data_dir 字段方便上层日志/调试。
        effective_data_dir = cli_data_dir or legacy_data_dir

    future_list = data_src.get("future_list_path", str(_BASE / "data" / "future_list.csv"))
    industry_map = data_src.get("industry_map_path", str(_BASE / "data" / "industry_map.csv"))

    return RunConfig(
        enabled_strategies   = enabled,
        adapter_type         = adapter_type,
        adapter_params       = adapter_cfg,
        per_strategy_capital = float(cap_yaml.get("per_strategy_capital", 1_000_000)),
        universe_level       = uni_level,
        universe_items       = uni_items,
        start                = pd.Timestamp(start) if start else None,
        end                  = ((pd.Timestamp(end) + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1))
                                if end and len(str(end)) == 10 else pd.Timestamp(end) if end else None),
        warmup_bars          = int(warmup),
        output_dir           = out_dir,
        output_prefix        = out_prefix,
        data_dir             = effective_data_dir,
        data_source_type     = ds_type,
        data_source_params   = ds_params,
        future_list_path     = future_list,
        industry_map_path    = industry_map,
    )
