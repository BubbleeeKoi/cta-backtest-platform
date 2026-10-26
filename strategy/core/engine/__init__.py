"""
core/engine/  ——  回测引擎

模块划分:
    loop.py            主时间循环 / 多策略调度（BacktestEngine 主类）
    pre_build.py       策略并行预算（spawn 子进程批量预算，结果回灌
                       Strategy.set_prebuilt_signals）
    signal_pipeline.py Signal / Fill 流转辅助（打 signal_id、回灌 fill）

公共符号统一从本包根导出，``from core.engine import BacktestEngine`` 即可。
"""
from .loop import BacktestEngine, EngineResult, StrategySlot

__all__ = ["BacktestEngine", "EngineResult", "StrategySlot"]
