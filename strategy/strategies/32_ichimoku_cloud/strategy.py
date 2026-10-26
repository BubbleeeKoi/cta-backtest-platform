"""Completed-bar adapter; decisions are retained in _source.py."""
from .._source_program import SourceProgramStrategy
from . import params as defaults


class Strategy(SourceProgramStrategy):
    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        merged = {"timeframe": getattr(defaults, "TIMEFRAME", "1h"),
                  "direction": getattr(defaults, "DIRECTION", "both"),
                  "volume": getattr(defaults, "VOLUME", 1),
                  "source_params": getattr(defaults, "SOURCE_PARAMS", {})}
        merged.update(params or {})
        super().__init__(strategy_id, contract_info, data_pool, merged)
