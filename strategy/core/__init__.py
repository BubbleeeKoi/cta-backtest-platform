"""
core/  ——  回测引擎实现

仅回测使用。实盘部署时不需要复制 core/，但要部署同源的 framework/。

主公共 API（``from core import ...``）：
    BacktestEngine        回测引擎（时间游标 + 多策略调度）
    BacktestDataPool      DataPool 回测侧实现
    TradeAccountant       记账（Fill → trades_df / nav_df）
    NotionalSizer         固定名义市值手数计算
    build_adapter         PortfolioAdapter 工厂（按配置返回 PassThrough /
                          Capped / Dedup 等具体子类）
    load_run_config       读取并合并 6 个 yaml + CLI 覆盖

其它公开符号（``from core.<submodule> import ...``）：
    core.engine.StrategySlot / BacktestEngine
    core.matcher.Matcher
    core.portfolio_adapter.{BasePortfolioAdapter,PassThroughAdapter,
                            CappedCapitalAdapter, ConflictDedupAdapter}
    core.sizing.BaseSizer
    core.data_loader.{load_future_list, load_industry_map,
                      load_symbol_data, get_tradeable_symbols,
                      symbol_from_contract_info}
    core.config_loader.{RunConfig, DEFAULT_CONFIG_DIR}
"""
from .accounting import TradeAccountant
from .config_loader import load_run_config
from .data_pool import BacktestDataPool
from .engine import BacktestEngine
from .portfolio_adapter import build_adapter
from .sizing import NotionalSizer, FixedLotSizer

__all__ = [
    "BacktestEngine",
    "BacktestDataPool",
    "TradeAccountant",
    "NotionalSizer",
    "FixedLotSizer",
    "build_adapter",
    "load_run_config",
]
