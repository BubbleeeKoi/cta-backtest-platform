from types import SimpleNamespace

import pandas as pd

from framework.types import FILL_FILLED, OFFSET_CLOSE, OFFSET_OPEN, Fill
from performance.capital_curve import build_capital_curves, save_capital_plots


class Pool:
    def get_all_bars(self, symbol, copy=False):
        index = pd.to_datetime([
            "2024-01-02 15:00", "2024-01-03 15:00", "2024-01-04 15:00",
        ])
        return pd.DataFrame({
            "tradingday": index.normalize(), "close": [110.0, 120.0, 105.0],
        }, index=index)

    def contract_info(self, symbol):
        return {"point": 10, "commission": 2, "type": 0}


def fill(day, price, direction, offset):
    return Fill(
        fill_id=day, order_id=day, signal_id=day, strategy_id="demo",
        symbol="RB", contract="RB", status=FILL_FILLED,
        fill_datetime=pd.Timestamp(f"2024-01-{day} 09:00"),
        fill_price=price, fill_volume=1, direction=direction, offset=offset,
        commission=0, session="ALL",
    )


def test_open_position_is_marked_daily_and_close_is_realized(tmp_path):
    curves = build_capital_curves(
        [fill("02", 100, 1, OFFSET_OPEN), fill("04", 105, -1, OFFSET_CLOSE)],
        Pool(), [SimpleNamespace(strategy_id="demo", symbol="RB")],
        {"demo": 1000},
    )
    assert curves["equity"].tolist() == [1098, 1198, 1046]
    assert curves["daily_pnl"].tolist() == [98, 100, -152]
    assert curves["unrealized_pnl"].tolist() == [100, 200, 0]
    assert curves["realized_pnl"].tolist() == [-2, -2, 46]
    assert len(save_capital_plots(curves, tmp_path)) == 1
    assert (tmp_path / "demo" / "capital_RB.png").is_file()


def test_charts_are_separated_by_strategy(tmp_path):
    curves = pd.DataFrame([
        {"date": "2024-01-02", "strategy": "first", "symbol": "RB",
         "initial_capital": 1000, "equity": 1010},
        {"date": "2024-01-02", "strategy": "second", "symbol": "RB",
         "initial_capital": 1000, "equity": 990},
    ])
    paths = save_capital_plots(curves, tmp_path)
    assert set(paths) == {
        tmp_path / "first" / "capital_RB.png",
        tmp_path / "second" / "capital_RB.png",
    }
    assert all(path.is_file() for path in paths)
