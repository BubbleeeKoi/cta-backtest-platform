"""Daily marked-to-market capital curves for each strategy and symbol."""

from __future__ import annotations

import re
from collections import deque
from pathlib import Path
from typing import Iterable

import pandas as pd

from core.accounting import _calc_comm, _resolve_commission
from framework.types import FILL_FILLED, FILL_PARTIAL, OFFSET_OPEN, Fill


COLUMNS = [
    "date", "strategy", "symbol", "initial_capital", "realized_pnl",
    "unrealized_pnl", "equity", "daily_pnl", "net_value",
]


def build_capital_curves(
    fills: Iterable[Fill], data_pool, slots, capital_by_strategy: dict[str, float],
    start: pd.Timestamp | None = None, end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Mark open positions at each trading day's last available bar close.

    Commissions are charged when their fills occur. Closing profit is realized
    on the actual close fill, while open positions contribute unrealized PnL.
    This series is independent of the legacy closed-trade daily_pnl report.
    """
    events: dict[tuple[str, str], list[Fill]] = {}
    for fill in fills:
        if (fill.status in (FILL_FILLED, FILL_PARTIAL)
                and fill.fill_volume > 0 and fill.fill_price is not None
                and fill.fill_datetime is not None):
            events.setdefault((fill.strategy_id, fill.symbol), []).append(fill)

    rows = []
    for strategy, symbol in sorted({(s.strategy_id, s.symbol) for s in slots}):
        capital = float(capital_by_strategy[strategy])
        if capital <= 0:
            raise ValueError(f"{strategy}: initial capital must be positive")
        bars = data_pool.get_all_bars(symbol, copy=False)
        if bars is None or bars.empty:
            continue
        if start is not None:
            bars = bars[bars.index >= start]
        if end is not None:
            bars = bars[bars.index <= end]
        if bars.empty:
            continue
        closes = bars.sort_index().groupby("tradingday", sort=True).tail(1)
        closes = closes.sort_index()

        ci = data_pool.contract_info(symbol)
        point = float(ci.get("point", 10))
        rate, is_fixed = _resolve_commission(ci)
        ordered = sorted(events.get((strategy, symbol), []), key=lambda f: f.fill_datetime)
        lots: dict[int, deque[list[float]]] = {1: deque(), -1: deque()}
        realized = 0.0
        previous_equity = capital
        event_index = 0

        for ts, bar in closes.iterrows():
            while event_index < len(ordered) and ordered[event_index].fill_datetime <= ts:
                fill = ordered[event_index]
                event_index += 1
                price = float(fill.fill_price)
                volume = int(fill.fill_volume)
                direction = int(fill.direction)
                realized -= _calc_comm(rate, is_fixed, price, point, volume)
                if fill.offset == OFFSET_OPEN:
                    lots[direction].append([price, volume])
                else:
                    remaining = volume
                    opened = lots[-direction]
                    while remaining and opened:
                        entry_price, open_volume = opened[0]
                        matched = min(remaining, int(open_volume))
                        realized += (price - entry_price) * -direction * point * matched
                        remaining -= matched
                        open_volume -= matched
                        if open_volume:
                            opened[0][1] = open_volume
                        else:
                            opened.popleft()

            mark = float(bar["close"])
            unrealized = sum(
                (mark - entry_price) * direction * point * volume
                for direction, open_lots in lots.items()
                for entry_price, volume in open_lots
            )
            equity = capital + realized + unrealized
            rows.append({
                "date": pd.Timestamp(bar["tradingday"]).date(),
                "strategy": strategy,
                "symbol": symbol,
                "initial_capital": capital,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "equity": equity,
                "daily_pnl": equity - previous_equity,
                "net_value": equity / capital,
            })
            previous_equity = equity

    return pd.DataFrame(rows, columns=COLUMNS)


def save_capital_plots(curves: pd.DataFrame, output_dir: Path) -> list[Path]:
    """Write each strategy's symbol charts into its own subdirectory."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for (strategy, symbol), group in curves.groupby(["strategy", "symbol"], sort=True):
        group = group.sort_values("date")
        initial = float(group["initial_capital"].iloc[0])
        fig, ax = plt.subplots(figsize=(11, 4.5))
        ax.plot(pd.to_datetime(group["date"]), group["equity"], linewidth=1.4)
        ax.axhline(initial, color="gray", linestyle="--", linewidth=0.8)
        ax.set(title=f"{strategy} / {symbol}", xlabel="Date", ylabel="Equity (CNY)")
        ax.grid(alpha=0.25)
        fig.tight_layout()
        safe_strategy = re.sub(r"[^A-Za-z0-9_.-]", "_", str(strategy))
        safe_symbol = re.sub(r"[^A-Za-z0-9_.-]", "_", str(symbol))
        strategy_dir = output_dir / (safe_strategy.strip(".") or "strategy")
        strategy_dir.mkdir(parents=True, exist_ok=True)
        path = strategy_dir / f"capital_{safe_symbol}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        paths.append(path)
    return paths
