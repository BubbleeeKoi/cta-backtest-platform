"""Fixed-lot selection must not scale with capital or truncate exits."""
from pathlib import Path
import sys
import argparse
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config_loader import load_run_config, DEFAULT_CONFIG_DIR
from core.portfolio_adapter import build_adapter
from core.sizing import FixedLotSizer, NotionalSizer
from framework import Signal, SIGNAL_ENTRY, SIGNAL_EXIT, OFFSET_OPEN, OFFSET_CLOSE, ORDER_MARKET
from run_backtest import _positive_lots
from web_app import build_command


def signal(offset=OFFSET_OPEN, hint=None):
    ts = pd.Timestamp("2025-01-02 15:00")
    return Signal(symbol="RB", action_datetime=ts, bar_datetime=ts,
                  signal_kind=SIGNAL_ENTRY if offset == OFFSET_OPEN else SIGNAL_EXIT,
                  direction=1 if offset == OFFSET_OPEN else -1, offset=offset,
                  order_type=ORDER_MARKET, price=3000., session="ALL",
                  strategy_id="test", volume_hint=hint)


@pytest.mark.parametrize("kind", ["passthrough", "capped_capital", "conflict_dedup"])
def test_fixed_entry_and_full_exit_across_web_adapters(kind):
    adapter = build_adapter(kind, {"RB":{"point":10}}, {"test":FixedLotSizer(1, 1_000_000)})
    entry = adapter.process(pd.Timestamp("2025-01-02"), {"test":[signal()]}, {"RB":3000.})
    assert entry[0].volume == 1  # not round(1,000,000 / 30,000)
    closing = adapter.process(pd.Timestamp("2025-01-03"), {"test":[signal(OFFSET_CLOSE, 7)]}, {"RB":3000.})
    assert closing[0].volume == 7  # never replace a full close with one lot


def test_fixed_size_does_not_change_when_capital_or_prices_change():
    for capital in (100_000, 1_000_000, 10_000_000):
        sizer = FixedLotSizer(1, capital)
        assert sizer.allocated_capital == capital
        assert sizer.calc_volume(3000., 10.) == sizer.calc_volume(8000., 100.) == 1
    assert NotionalSizer(1_000_000).calc_volume(3000., 10.) == 33


def test_volume_override_reaches_template_and_source_strategy_without_changing_capital():
    cfg = load_run_config(DEFAULT_CONFIG_DIR, {"strategy":["ma5ma10","06_macd_trend"], "volume":1})
    assert all(s["params"]["volume"] == 1 for s in cfg.enabled_strategies)
    assert cfg.per_strategy_capital == 1_000_000


def test_web_forwards_lots_and_blank_preserves_previous_behavior():
    command = build_command({"strategy":"ma5ma10", "volume":"1"})
    assert command[command.index("--volume")+1] == "1"
    assert "--volume" not in build_command({"volume":""})


@pytest.mark.parametrize("value", ["0", "-1"])
def test_cli_rejects_nonpositive_lots(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _positive_lots(value)
