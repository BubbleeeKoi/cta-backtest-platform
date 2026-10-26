"""Framework adapter for the paper's daily continuous-position DMN signal.

At the first minute of trading day t+1, rebalance to the target computed from
day t's close. This avoids trading at a close that was needed to form the signal.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from framework import Bar, Signal, Strategy as BaseStrategy
from framework.types import OFFSET_CLOSE, OFFSET_OPEN, ORDER_EXACT, SIGNAL_ENTRY, SIGNAL_EXIT
from framework.snapshot import HistoryView, Snapshot

from .model import (
    FEATURE_NAMES, LOOKBACK, daily_features, default_model_path, load_network,
    valid_sample_days,
)


class Strategy(BaseStrategy):
    REQUIRED_UNIVERSE = "self"
    SESSION_NAMES = ["全天"]
    SUPPORTS_BATCH_PREBUILD = False

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self.model_path = Path(self.params.get("model_path") or default_model_path()).resolve()
        self.capital = float(self.params.get("allocated_capital", 1_000_000.0))
        raw_max_leverage = self.params.get("max_leverage")
        self.max_leverage = float(raw_max_leverage) if raw_max_leverage is not None else None
        self.point = float(self.contract_info.get("point", 10) or 10)
        if self.capital <= 0 or self.point <= 0 or (
            self.max_leverage is not None and self.max_leverage <= 0
        ):
            raise ValueError("allocated_capital, contract point and optional max_leverage must be positive")
        self._targets: dict[pd.Timestamp, tuple[float, float]] = {}
        self._last_tradingday: pd.Timestamp | None = None
        self._prepared = False
        self.target_vol = 0.15

    def on_init(self, history: HistoryView) -> None:
        import torch

        if not self.model_path.is_file():
            raise FileNotFoundError(f"DMN model missing: {self.model_path}; run the training command first")
        model, metadata = load_network(str(self.model_path))
        if int(metadata["lookback"]) != LOOKBACK:
            raise ValueError("model lookback differs from strategy code")
        self.target_vol = float(metadata["target_vol"])
        valid_end = pd.Timestamp(metadata["valid_end"]).normalize()
        bars = self.data_pool.get_all_bars(self.symbol, copy=False)
        if bars is None or bars.empty:
            self._prepared = True
            return
        features = daily_features(bars)
        values = features.loc[:, FEATURE_NAMES].to_numpy(dtype=np.float32)
        positions = valid_sample_days(features, require_label=False)
        # Model weights are fixed after validation. Only later dates are traded.
        positions = [i for i in positions if pd.Timestamp(features.iloc[i]["next_day"]) > valid_end]
        if positions:
            with torch.no_grad():
                for start in range(0, len(positions), 512):
                    block = positions[start:start + 512]
                    windows = np.stack([values[i - LOOKBACK + 1:i + 1] for i in block])
                    predictions = model(torch.from_numpy(windows)).numpy()
                    for i, prediction in zip(block, predictions):
                        next_day = pd.Timestamp(features.iloc[i]["next_day"]).normalize()
                        sigma = float(features.iloc[i]["sigma_ann"])
                        self._targets[next_day] = (float(prediction), sigma)
        self._prepared = True

    def _signal(self, bar: Bar, direction: int, offset: str, volume: int) -> Signal:
        return Signal(
            symbol=bar.symbol,
            action_datetime=bar.timestamp,
            bar_datetime=bar.timestamp,
            signal_kind=SIGNAL_ENTRY if offset == OFFSET_OPEN else SIGNAL_EXIT,
            direction=direction,
            offset=offset,
            order_type=ORDER_EXACT,
            session="全天",
            price=float(bar.open),
            volume_hint=volume,
            tag="daily_rebalance",
        )

    def on_bar(self, bar: Bar, snapshot: Snapshot) -> list[Signal]:
        if not self._prepared:
            raise RuntimeError("DMN strategy was not initialized; check the on_init warning")
        day = pd.Timestamp(bar.tradingday).normalize()
        if day == self._last_tradingday:
            return []
        self._last_tradingday = day
        target = self._targets.get(day)
        if target is None or not np.isfinite(bar.open) or bar.open <= 0:
            return []
        signal, sigma = target
        exposure = signal * self.target_vol / sigma
        if self.max_leverage is not None:
            exposure = np.clip(exposure, -self.max_leverage, self.max_leverage)
        wanted = int(np.rint(self.capital * exposure / (float(bar.open) * self.point)))
        current = int(self.position.net_volume)
        if wanted == current:
            return []
        signals: list[Signal] = []
        if current and (wanted == 0 or np.sign(wanted) != np.sign(current)):
            signals.append(self._signal(bar, -int(np.sign(current)), OFFSET_CLOSE, abs(current)))
            current = 0
        if wanted and current and abs(wanted) < abs(current):
            signals.append(self._signal(bar, -int(np.sign(current)), OFFSET_CLOSE,
                                        abs(current) - abs(wanted)))
        elif wanted and (current == 0 or abs(wanted) > abs(current)):
            signals.append(self._signal(bar, int(np.sign(wanted)), OFFSET_OPEN,
                                        abs(wanted) - abs(current)))
        return signals
