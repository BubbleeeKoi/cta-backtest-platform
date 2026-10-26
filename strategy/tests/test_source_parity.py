"""Source provenance, execution, and completed-bar transport checks."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from framework import Bar
from strategies import _CATEGORY_GROUPS, load_strategy_class
from strategies._source_program import SourceProgramStrategy
from strategies._source_compat import std, source_datetime

NAMES = sorted(set.union(*list(_CATEGORY_GROUPS.values())[:4]))


def instance(name, timeframe="1h", **params):
    return load_strategy_class(name)(name, {"symbol": "RB"}, None,
                                    dict(timeframe=timeframe, direction="both", **params))


def row(i, price=2400):
    return dict(timestamp=pd.Timestamp("2020-01-01") + pd.Timedelta(days=i),
                open=price-1, high=price+15, low=price-15, close=price,
                volume=500., oi=10000.+i)


def seed(strategy, values):
    for stream in strategy._streams:
        stream["history"].extend(values[-stream["length"]:-1])
        strategy._update_frame(stream, values[-1])
        strategy._api.changed.add(id(stream["frame"]))
        strategy._api.changed_stamps.add(stream["frame"].iloc[-1]["datetime"])


@pytest.mark.parametrize("name", NAMES)
def test_each_program_is_pinned_to_local_original(name):
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    path = ROOT / "strategies" / name / "_source.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest[name]["program_sha256"]
    assert isinstance(instance(name), SourceProgramStrategy)
    assert "from tqsdk" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("timeframe", ["15m", "1h", "1d"])
@pytest.mark.parametrize("name", NAMES)
def test_each_source_decides_on_nonempty_history(name, timeframe):
    strategy = instance(name, timeframe)
    if name not in {"04_dual_thrust", "25_multiperiod_ma"}:
        assert {"15m":900, "1h":3600, "1d":86400}[timeframe] in {s["duration"] for s in strategy._streams}
    if name in {"23_pivot_point", "24_r_breaker"}:
        assert [s["previous"] for s in strategy._streams] == [timeframe != "1d", False]
    count = max(s["length"] for s in strategy._streams)
    rng = np.random.default_rng(77)
    prices = 2400 + rng.normal(0, 15, count+3).cumsum()
    values = [row(i, float(p)) for i, p in enumerate(prices)]
    seed(strategy, values[:-3])
    for value in values[-3:]:
        for stream in strategy._streams:
            strategy._update_frame(stream, value)
            strategy._api.changed.add(id(stream["frame"]))
            strategy._api.changed_stamps.add(stream["frame"].iloc[-1]["datetime"])
        strategy._day_open = value["open"]
        with np.errstate(divide="ignore", invalid="ignore"):
            target = strategy._decision(value)
        assert target is None or isinstance(target, int)
        if target is not None:
            strategy.position.long_volume = max(target, 0)
            strategy.position.short_volume = max(-target, 0)


def test_source_grid_global_state_is_isolated_per_symbol():
    a, b = instance("12_grid_trading"), instance("12_grid_trading")
    a._source_namespace["grid_has_position"][2400] = True
    assert not b._source_namespace["grid_has_position"][2400]


def test_original_orb_minute_carry_is_preserved():
    strategy = instance("13_opening_range_breakout")
    assert (strategy._source_namespace["ORB_END_HOUR"],
            strategy._source_namespace["ORB_END_MIN"]) == (10, 0)
    source = (ROOT/"strategies"/"13_opening_range_breakout"/"_source.py").read_text(encoding="utf-8")
    assert "if ORB_END_MIN >= 60:" in source  # not just a runtime fallback


def test_sdk_sample_standard_deviation():
    values = pd.Series([1., 2., 4., 9.])
    assert std(values, 4).iloc[-1] == pytest.approx(np.std(values, ddof=1))


def test_sdk_atr_boll_and_rsi_reference_values():
    from strategies._source_compat import ATR, BOLL, RSI
    frame = pd.DataFrame(dict(close=[10.,12.,11.], high=[11.,13.,12.], low=[9.,11.,10.]))
    value = ATR(frame, 2)
    assert pd.isna(value.iloc[0]) and pd.isna(value.iloc[1])
    assert value.iloc[2] == pytest.approx(2.5)
    assert BOLL(frame,3,2).top.iloc[-1] == pytest.approx(13.)
    assert RSI(frame,2).iloc[-1] == pytest.approx(100/3)


def test_wall_clock_decoding_is_independent_of_host_timezone():
    value = pd.Timestamp("2025-01-02 09:30").value / 1e9
    assert source_datetime(value).hour == 9


def bar(stamp, *, daily=False, volume=100, price=2400, td=None):
    stamp = pd.Timestamp(stamp)
    return Bar("RB", stamp, pd.Timestamp(td) if td else stamp.normalize(),
               price, price+1, price-1, price, volume, is_daily_close=daily)


def test_daily_aggregate_replaces_execution_row_and_publishes_at_close():
    strategy = instance("01_double_ma", "1d", _daily_event_source=True)
    strategy.on_bar(bar("2025-01-02 09:05", volume=100), None)
    strategy.on_bar(bar("2025-01-02 15:00", daily=True, volume=1000), None)
    history = strategy._streams[0]["history"]
    assert len(history) == 1
    assert history[-1]["volume"] == 1000
    strategy.on_bar(bar("2025-01-03 09:05"), None)
    assert len(history) == 1


def test_daily_night_session_uses_exchange_trading_day():
    strategy = instance("01_double_ma", "1d")
    strategy.on_bar(bar("2025-01-02 21:00", td="2025-01-03"), None)
    strategy.on_bar(bar("2025-01-03 09:00", td="2025-01-03"), None)
    assert len(strategy._streams[0]["history"]) == 0
    strategy.on_bar(bar("2025-01-06 09:00"), None)
    assert strategy._streams[0]["history"][-1]["volume"] == 200


def test_formula_and_thresholds_survive_regeneration_from_desktop():
    sys.path.insert(0, str(ROOT / "tools"))
    from sync_source_programs import generate
    originals = list(Path.home().glob("Desktop/*/*/tqsdk-strategies-main/strategies"))
    if not originals:
        pytest.skip("Original desktop folder is not on this computer")
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    for name in NAMES:
        original = (originals[0] / (name + ".py")).read_bytes()
        assert hashlib.sha256(original).hexdigest() == manifest[name]["source_sha256"]
        regenerated = generate(original.decode("utf-8-sig"), int(name[:2]) >= 64, name)
        assert regenerated == (ROOT / "strategies" / name / "_source.py").read_text(encoding="utf-8")


def test_all_h5_products_in_universe_even_if_not_tradeable_today(tmp_path):
    from run_backtest import _resolve_universe
    for name in ("RB", "IF", "WR"):
        (tmp_path / (name+".h5")).touch()
    assert _resolve_universe("product", [], "not-used.csv", str(tmp_path)) == ["IF", "RB", "WR"]


def test_warmup_never_reads_future_rows():
    from types import SimpleNamespace
    frame = pd.DataFrame([dict(open=p, high=p+1, low=p-1, close=p, volume=1., oi=1.,
                               tradingday=pd.Timestamp(day)) for day,p in
                          [("2025-01-02", 100.), ("2025-01-03", 200.), ("2030-01-02", 99999.)]],
                         index=pd.to_datetime(["2025-01-02 15:00", "2025-01-03 15:00", "2030-01-02 15:00"]))
    pool = SimpleNamespace(get_all_bars=lambda *args, **kwargs: frame)
    history = SimpleNamespace(own_bars=frame.iloc[:2], data_pool=pool)
    strategy = instance("01_double_ma", "1d")
    strategy.on_init(history)
    assert max(v["close"] for v in strategy._streams[0]["history"]) < 99999


def test_end_date_covers_the_complete_last_day():
    from core.config_loader import load_run_config, DEFAULT_CONFIG_DIR
    config = load_run_config(DEFAULT_CONFIG_DIR, {"end": "2025-12-31"})
    assert config.end == pd.Timestamp("2025-12-31 23:59:59.999999999")


def test_financial_futures_execution_event_is_not_lost():
    from data_sources.hdf5_daily_0905 import _event_positions
    stamps = pd.to_datetime(["2025-01-02 09:31", "2025-01-02 10:00", "2025-01-02 15:00"])
    assert _event_positions(stamps, stamps.normalize()).tolist() == [0, 2]


def test_zero_volume_vwap_window_keeps_target_without_crashing():
    strategy = instance("18_vwap_mean_reversion")
    values = [dict(row(i), volume=0.) for i in range(200)]
    seed(strategy, values)
    assert strategy._decision(values[-1]) is None


def test_intraday_bar_is_published_on_its_last_minute():
    strategy = instance("01_double_ma", "1h")
    strategy.on_bar(bar("2025-01-02 09:00"), None)
    strategy.on_bar(bar("2025-01-02 09:59", price=2410), None)
    history = strategy._streams[0]["history"]
    assert len(history) == 1
    assert history[-1]["close"] == 2410
    strategy.on_bar(bar("2025-01-02 10:00"), None)
    assert len(history) == 1


def test_dual_thrust_close_uses_completed_time_not_bucket_start():
    strategy = instance("04_dual_thrust", "15m")
    seed(strategy, [row(i) for i in range(6)])
    strategy.position.long_volume = 1
    strategy.on_bar(bar("2025-01-02 14:45"), None)
    signals = strategy.on_bar(bar("2025-01-02 14:59"), None)
    assert len(signals) == 1
    assert signals[0].offset == "close"
    assert strategy._api.quote.datetime.endswith("14:59:00")


def test_double_ma_golden_cross_and_target_persistence():
    strategy = instance("01_double_ma")
    values = [row(i, 2400.) for i in range(29)] + [row(29, 2410.)]
    seed(strategy, values)
    assert strategy._decision(values[-1]) == 1
    next_row = row(30, 2410.)
    strategy._update_frame(strategy._streams[0], next_row)
    assert strategy._decision(next_row) == 1  # no fill yet: retain target


def test_daily_pivot_levels_use_yesterday_not_the_signal_day():
    strategy = instance("23_pivot_point", "1d")
    values = [row(i, 2400.) for i in range(499)] + [row(499, 2450.)]
    seed(strategy, values)
    strategy._decision(values[-1])
    assert strategy._program.gi_frame.f_locals["pp"] == pytest.approx(2400.)
