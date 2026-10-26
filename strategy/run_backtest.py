"""
run_backtest.py  ——  回测入口

用法:
    # 默认（按 config/ 下 6 个 yaml 跑）
    python run_backtest.py

    # 单策略
    python run_backtest.py --strategy jerome

    # 多策略独立批量（强制 PassThrough）
    python run_backtest.py --strategy all --adapter passthrough

    # 多策略资金限额组合
    python run_backtest.py --strategy all --adapter capped_capital

    # 限品种 / 限时段
    python run_backtest.py --strategy jerome --symbols RB MA CU \
                          --start 2024-01-01 --end 2024-12-31
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让 framework / core / strategies 都能直接 import
_BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(_BASE))

from tqdm import tqdm

from core import (
    BacktestDataPool,
    BacktestEngine,
    NotionalSizer,
    FixedLotSizer,
    TradeAccountant,
    build_adapter,
    load_run_config,
)
from core.config_loader import DEFAULT_CONFIG_DIR
from core.data_loader import (
    get_tradeable_symbols,
    load_future_list,
    load_industry_map,
)
from core.engine import StrategySlot
from data_sources import HDF5Daily0905Source, build_source, list_source_types
from framework import ActionRecorder, SignalRecorder
from performance.capital_curve import build_capital_curves, save_capital_plots
from strategies import load_strategy_class


def _positive_lots(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("手数必须是正整数")
    return number


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="CTA 团队策略回测",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--strategy", nargs="+", default=None,
                   help="策略选择：'all' / 'jerome' / 'jerome other'（留空走 config/strategies.yaml）")
    p.add_argument("--adapter", default=None,
                   help="组合层：passthrough | capped_capital | conflict_dedup")
    p.add_argument("--symbols", nargs="+", default=None,
                   help="品种列表（留空走 universe.yaml 或全市场）")
    p.add_argument("--level", default=None, choices=["product", "contract"],
                   help="品种级 vs 合约级")
    p.add_argument("--start", default=None, help="回测起始日 YYYY-MM-DD")
    p.add_argument("--end",   default=None, help="回测结束日 YYYY-MM-DD")
    p.add_argument("--timeframe", default=None, choices=["15m", "1h", "1d"],
                   help="所有策略的 K 线周期：15m | 1h | 1d")
    p.add_argument("--direction", default=None, choices=["long", "short", "both"],
                   help="所有策略的交易方向：long | short | both")
    p.add_argument("--volume", type=_positive_lots, default=None,
                   help="固定基础开仓手数，例如 1；网格为每层手数；不填保留原配置")
    p.add_argument("--data-dir", default=None, help="HDF5 数据目录（仅 hdf5_index 数据源生效）")
    p.add_argument("--data-source", default=None,
                   choices=list_source_types(),
                   help=f"数据源类型；可选: {list_source_types()}（默认走 config/data_source.yaml）")
    p.add_argument("--prefix",   default=None, help="输出文件名前缀")
    p.add_argument("--out-dir",  default=None, help="输出目录（默认 output/）")
    p.add_argument("--warmup-bars", type=int, default=None, help="预热 bar 数")
    p.add_argument("--config-dir", default=str(DEFAULT_CONFIG_DIR),
                   help="config 目录（默认 strategy/config/）")
    p.add_argument("--no-signals", action="store_true",
                   help="不输出 signals/ 对账 CSV（默认输出）")
    p.add_argument("--no-actions", action="store_true",
                   help="不输出 actions/ 动作事件流 CSV（默认输出）")
    p.add_argument("--no-plots", action="store_true", help="跳过逐策略逐品种 PNG，保留 CSV 和报告")
    return p.parse_args()


def _resolve_universe(level: str, items: list[str], future_list, data_dir: str) -> list[str]:
    if level == "contract":
        raise NotImplementedError(
            "contract 级回测尚未实现（需接入 main_contract/ 展期数据）。"
        )
    if items:
        return list(items)
    available = sorted(path.stem for path in Path(data_dir).glob("*.h5"))
    if available:
        # Research includes delisted/currently non-tradeable products whenever
        # their historical data exists; today's trade flag is not a history filter.
        return available
    return get_tradeable_symbols(future_list_path=str(future_list), data_dir=data_dir)


def main() -> int:
    args = _parse_args()

    # ── 解析 CLI 覆盖 ──
    cli = {
        "strategy":    args.strategy if (args.strategy is None or len(args.strategy) > 1)
                       else (args.strategy[0] if args.strategy else None),
        "adapter":     args.adapter,
        "symbols":     args.symbols,
        "level":       args.level,
        "start":       args.start,
        "end":         args.end,
        "timeframe":   args.timeframe,
        "direction":   args.direction,
        "volume":      args.volume,
        "data_dir":    args.data_dir,
        "data_source": args.data_source,
        "prefix":      args.prefix,
        "out_dir":     args.out_dir,
        "warmup_bars": args.warmup_bars,
    }
    # 1 个 strategy 时把 list 折叠成 str
    if isinstance(cli["strategy"], list) and len(cli["strategy"]) == 1:
        cli["strategy"] = cli["strategy"][0]
    cli = {k: v for k, v in cli.items() if v is not None}

    cfg = load_run_config(args.config_dir, cli)

    # ── 加载 future_list + industry_map + universe ──
    future_list = load_future_list(cfg.future_list_path)
    industry_map = load_industry_map(cfg.industry_map_path)
    # universe 解析仍按 cfg.data_dir 走（hdf5_index 时 = h5 目录；其它 source
    # 时调用方应在 yaml 里显式提供 universe_items 而不是靠"目录扫描"兜底）。
    symbols = _resolve_universe(cfg.universe_level, cfg.universe_items,
                                cfg.future_list_path, cfg.data_dir)
    if not symbols:
        print("[ERROR] universe 为空（请检查 universe.yaml 或 --symbols）")
        return 2

    # 所有策略共用本次回测选择的周期。日线模式使用每日事件源；
    # 15m / 1h 模式使用原始分钟源，由各策略内部聚合周期 K 线。
    packages = [s["package"] for s in cfg.enabled_strategies]
    configured_timeframes = {
        str((s.get("params") or {}).get("timeframe")).lower()
        for s in cfg.enabled_strategies
        if (s.get("params") or {}).get("timeframe")
    }
    if len(configured_timeframes) > 1:
        raise ValueError("同一次回测中的策略必须使用相同 K 线周期")
    timeframe = next(iter(configured_timeframes), None)
    minute_required = any(name in {"04_dual_thrust", "13_opening_range_breakout",
                                   "25_multiperiod_ma"} for name in packages)
    if timeframe == "1d" and not minute_required:
        if cfg.data_source_type != "hdf5_index":
            raise ValueError("日线回测目前需要 hdf5_index 数据源")
        source = HDF5Daily0905Source(cfg.data_dir)
    elif timeframe in {None, "15m", "1h", "1d"}:
        source = build_source(cfg.data_source_type, cfg.data_source_params)
    else:
        raise ValueError(f"不支持的 K 线周期：{timeframe}，可选 15m、1h、1d")
    for strategy_config in cfg.enabled_strategies:
        strategy_config.setdefault("params", {})["_daily_event_source"] = timeframe == "1d" and not minute_required

    # ── 加载 DataPool（一次性加载到内存） ──
    print(f"\n{'='*60}")
    print(f"  CTA 回测  ({cfg.adapter_type})")
    print(f"{'='*60}")
    print(f"  策略数 : {len(cfg.enabled_strategies)}  → {[s['package'] for s in cfg.enabled_strategies]}")
    print(f"  品种数 : {len(symbols)}")
    print(f"  时段   : {cfg.start} → {cfg.end}")
    print(f"  数据源 : {source.describe()}")
    print(f"{'='*60}\n")

    data_pool = BacktestDataPool(
        symbols      = symbols,
        source       = source,
        future_list  = future_list,
        industry_map = industry_map,
    )
    actual_symbols = data_pool.list_universe()
    print(f"  加载成功品种: {len(actual_symbols)} / {len(symbols)}\n")

    # ── 实例化每个 (strategy × symbol) slot ──
    slots: list[StrategySlot] = []
    sizers: dict = {}

    for s_cfg in cfg.enabled_strategies:
        pkg = s_cfg["package"]
        try:
            StrategyClass = load_strategy_class(pkg)
        except Exception as e:
            print(f"  [WARN] 策略 {pkg} 加载失败：{e}")
            continue

        cap = float(s_cfg.get("capital", cfg.per_strategy_capital))
        volume = (s_cfg.get("params") or {}).get("volume")
        sizers[pkg] = FixedLotSizer(volume, cap) if volume is not None else NotionalSizer(cap)

        for sym in actual_symbols:
            ci = data_pool.contract_info(sym)
            # allocated_capital 既给 sizer 又给 accountant，二者必须共用同一份资金。
            params = dict(s_cfg.get("params") or {})
            params.setdefault("allocated_capital", cap)
            try:
                inst = StrategyClass(
                    strategy_id   = pkg,
                    contract_info = ci,
                    data_pool     = data_pool,
                    params        = params,
                )
                sessions = list(getattr(inst, "SESSION_NAMES", []) or ["ALL"])
                slots.append(StrategySlot(
                    strategy_id = pkg,
                    symbol      = sym,
                    instance    = inst,
                    sessions    = sessions,
                ))
            except Exception as e:
                tqdm.write(f"  [WARN] {pkg}/{sym} 实例化失败：{e}")

    if not slots:
        print("[ERROR] 没有可运行的 strategy × symbol 槽位")
        return 3

    # ── 构造 adapter + accountant ──
    contract_info_by_symbol = {s: data_pool.contract_info(s) for s in actual_symbols}
    adapter = build_adapter(
        cfg.adapter_type,
        contract_info_by_symbol,
        sizers,
        cfg.adapter_params,
    )
    allocated_capital_by_strategy = {
        s["package"]: float(s.get("capital", cfg.per_strategy_capital))
        for s in cfg.enabled_strategies
    }
    accountant = TradeAccountant(
        contract_info_by_symbol,
        allocated_capital_by_strategy,
    )

    # ── 跑引擎 ──
    signal_recorder: SignalRecorder | None = None if args.no_signals else SignalRecorder()
    action_recorder: ActionRecorder | None = None if args.no_actions else ActionRecorder()
    engine = BacktestEngine(
        data_pool       = data_pool,
        slots           = slots,
        adapter         = adapter,
        accountant      = accountant,
        warmup_bars     = cfg.warmup_bars,
        start           = cfg.start,
        end             = cfg.end,
        limit_max_wait  = 20,
        signal_recorder = signal_recorder,
        action_recorder = action_recorder,
    )
    result = engine.run()
    if result.errors:
        print(f"[ERROR] 回测存在 {len(result.errors)} 个执行错误，不写入成功结果。")
        for error in result.errors[:10]:
            print(error)
        return 3

    # ── 输出 ──
    out_dir = Path(cfg.output_dir)
    if not out_dir.is_absolute():
        out_dir = _BASE / out_dir
    out_trades    = out_dir / "trades"
    out_sym_daily = out_dir / "daily" / "symbol"
    out_port_daily= out_dir / "daily" / "portfolio"
    out_perf      = out_dir / "performance"
    out_eval      = out_dir / "evaluation"
    out_signals   = out_dir / "signals"
    out_actions   = out_dir / "actions"
    out_capital   = out_dir / "capital"
    for d in (out_trades, out_sym_daily, out_port_daily, out_perf, out_eval, out_signals, out_actions, out_capital):
        d.mkdir(parents=True, exist_ok=True)

    # 保存本次回测的通用参数，结果查看器据此按真实周期重建 K 线。
    metadata_dir = out_dir / "runs"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = metadata_dir / f"{cfg.output_prefix}.json"
    metadata_path.write_text(json.dumps({
        "prefix": cfg.output_prefix,
        "timeframe": next(iter(configured_timeframes), "1d"),
        "direction": [
            (s.get("params") or {}).get("direction", "both")
            for s in cfg.enabled_strategies
        ],
        "strategies": packages,
        "volume": {s["package"]: (s.get("params") or {}).get("volume") for s in cfg.enabled_strategies},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    prefix = cfg.output_prefix or "run"
    trades_path  = out_trades    / f"trades_{prefix}.csv"
    sym_path     = out_sym_daily / f"daily_pnl_{prefix}.csv"
    port_path    = out_port_daily/ f"daily_pnl_portfolio_{prefix}.csv"
    report_path  = out_perf      / f"performance_report_{prefix}.xlsx"
    eval_path    = out_eval      / f"evaluation_report_{prefix}.xlsx"
    signals_path = out_signals   / f"signals_{prefix}.csv"
    actions_path = out_actions   / f"actions_{prefix}.csv"

    result.trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
    result.nav_df.to_csv(sym_path, index=False, encoding="utf-8-sig")
    if not result.portfolio_nav_df.empty:
        result.portfolio_nav_df.to_csv(port_path, index=False, encoding="utf-8-sig")
    if signal_recorder is not None:
        signal_recorder.save(signals_path)
    if action_recorder is not None:
        action_recorder.save(actions_path)

    # 每个策略 × 品种的逐日盯市权益；开仓手续费与浮盈亏均在当日体现。
    capital_df = build_capital_curves(
        accountant.fills, data_pool, slots, allocated_capital_by_strategy,
        cfg.start, cfg.end,
    )
    capital_path = out_capital / f"capital_daily_{prefix}.csv"
    capital_df.to_csv(capital_path, index=False, encoding="utf-8-sig")
    # 每个回测前缀独立保存权益图，避免同一策略的不同方向/周期互相覆盖。
    capital_plots = [] if args.no_plots else save_capital_plots(capital_df, out_capital / prefix)

    # ── 简要统计 ──
    print(f"\n{'='*60}")
    print(f"  回测完成  耗时: {result.elapsed_sec:.1f}s")
    print(f"  策略数   : {result.n_strategies}")
    print(f"  品种数   : {result.n_symbols}")
    print(f"  总交易笔数: {len(result.trades_df):,}")
    if not result.trades_df.empty:
        total_pnl = result.trades_df["profit"].sum()
        win_rate = (result.trades_df["profit"] > 0).mean() * 100
        print(f"  总盈亏   : {total_pnl:,.0f} 元")
        print(f"  胜率     : {win_rate:.1f}%")
    if result.errors:
        print(f"  错误数   : {len(result.errors)}（仅显示前 3 条）")
        for e in result.errors[:3]:
            print(f"    - {e}")
    print(f"\n  交易流水 → {trades_path}")
    print(f"  每日净值 → {sym_path}")
    if not result.portfolio_nav_df.empty:
        print(f"  组合净值 → {port_path}")
    if signal_recorder is not None:
        print(f"  策略信号 → {signals_path}  ({len(signal_recorder)} 条)")
    if action_recorder is not None:
        print(f"  动作事件 → {actions_path}  ({len(action_recorder)} 条)")
    print(f"  每日权益 → {capital_path}  ({len(capital_plots)} 张品种曲线)")
    print(f"{'='*60}\n")

    # ── 绩效报告 / 深度评价 ──

    perf_root   = _BASE / "performance"
    perf_config = perf_root / "config.yaml"

    def write_completion():
        (metadata_dir / f"{prefix}.complete.json").write_text(json.dumps({
            "prefix": prefix, "status": "complete", "strategies": packages,
            "symbols": actual_symbols, "start": str(cfg.start), "end": str(cfg.end),
            "errors": 0, "no_trades": bool(result.trades_df.empty),
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    sys.path.insert(0, str(perf_root))
    try:
        from performance.symbol_core_overview import save_symbol_core_overview
        symbol_overview_path = out_capital / f"symbol_core_overview_{prefix}.xlsx"
        overview = save_symbol_core_overview(
            result.nav_df, result.trades_df, perf_config, symbol_overview_path,
        )
        print(f"  品种核心概览 → {symbol_overview_path}  ({len(overview)} 个品种)")
        if result.trades_df.empty:
            print("  [WARN] 无交易，跳过绩效与深度评价报告。")
            write_completion()
            return 0

        from src.run_all import run as _run_report          # type: ignore[import]
        from performance.evaluation import run as _run_eval # type: ignore[import]

        print("── 生成绩效报告 ────────────────────────────────────────")
        _run_report(trades_path, sym_path, report_path, perf_config)
        print(f"  绩效报告 → {report_path}")

        print("── 生成深度评价报告 ────────────────────────────────────")
        _run_eval(trades_path, sym_path, report_path, eval_path)
        print(f"  深度评价 → {eval_path}")
    except Exception as e:
        import traceback
        print(f"  [ERROR] 报告生成失败：{e}")
        traceback.print_exc()
        return 4
    finally:
        if str(perf_root) in sys.path:
            sys.path.remove(str(perf_root))

    write_completion()
    return 0


if __name__ == "__main__":
    sys.exit(main())
