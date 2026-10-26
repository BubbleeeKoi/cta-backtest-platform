import pandas as pd
import pytest
from performance.funding_metrics import account_metrics, margin_metrics


def test_drawdown_includes_initial_balance_and_keeps_denominators_distinct():
    curve = pd.DataFrame(dict(date=["2024-01-01","2024-01-02","2024-01-03"],
                              initial_capital=[100.]*3, equity=[90.,120.,80.]))
    value = account_metrics(curve, "2024-01-01", "2024-01-10")
    assert value["max_drawdown_amount"] == 40
    assert value["max_drawdown_initial_pct"] == 40
    assert value["max_drawdown_pct"] == pytest.approx(-100/3)
    assert value["total_return_pct"] == -20
    assert value["max_initial_loss_amount"] == 20
    assert value["max_initial_loss_pct"] == 20
    assert value["final_equity_multiple"] == .8
    assert value["simple_annual_return_pct"] == -730


def event(stamp, offset, direction, price=100):
    return dict(ts=stamp, event="fill_filled", fill_volume=1., fill_price=price,
                offset=offset, direction=direction, strategy_id="test")


def test_margin_includes_unclosed_positions_and_does_not_expose_flat_bars():
    bars = pd.DataFrame({"high":[110.,999.]}, index=pd.to_datetime(["2024-01-01 09:00","2024-01-01 09:01"]))
    opened = event("2024-01-01 09:00", "open", 1)
    held = margin_metrics([opened], bars, 10000., 10., .1, {"test"})
    assert held["max_margin_amount"] == 999
    closed = event("2024-01-01 09:01", "close", -1, 110.)
    flat = margin_metrics([opened,closed], bars, 10000., 10., .1, {"test"})
    assert flat["max_margin_amount"] == 110
    assert flat["max_margin_initial_pct"] == pytest.approx(1.1)


def test_reversing_at_one_timestamp_does_not_double_count_position():
    bars = pd.DataFrame({"high":[100.,120.]}, index=pd.to_datetime(["2024-01-01 09:00","2024-01-01 09:01"]))
    events = [event("2024-01-01 09:00","open",1),
              event("2024-01-01 09:01","close",-1),
              event("2024-01-01 09:01","open",-1)]
    value = margin_metrics(events, bars, 10000., 10., .1, {"test"})
    assert value["max_margin_amount"] == 120
    assert not margin_metrics([], bars, 10000., 10., .1, {"test"})["margin_available"]
