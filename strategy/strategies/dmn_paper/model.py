"""Daily features and the shared LSTM used by training and backtesting.

All features at day t use information available no later than that day's close.
The prediction is executed at the first bar of the following trading day.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

LOOKBACK = 63
TARGET_VOL = 0.15
FEATURE_NAMES = (
    "return_1", "return_21", "return_63", "return_126", "return_252",
    "macd_8_24", "macd_16_48", "macd_32_96",
)


def daily_features(minute_bars: pd.DataFrame) -> pd.DataFrame:
    """Convert product index minute bars to causal daily model inputs.

``tradingday`` is essential: a Chinese futures night session belongs to the
following trading day. There is deliberately no forward or backward fill.
"""
    if minute_bars is None or minute_bars.empty:
        return pd.DataFrame(columns=[*FEATURE_NAMES, "sigma_ann", "next_return", "next_day"])
    if "tradingday" not in minute_bars or "close" not in minute_bars:
        raise ValueError("minute bars require tradingday and close columns")
    frame = minute_bars.sort_index()
    tradingday = pd.to_datetime(frame["tradingday"]).dt.normalize()
    close = pd.to_numeric(frame["close"], errors="coerce").groupby(tradingday).last()
    close.index = pd.DatetimeIndex(close.index, name="tradingday")
    close = close.sort_index()
    close = close.where(close > 0)
    ret = close.pct_change(fill_method=None)
    # The 60-day EWM estimate is known after day t and used for day t+1.
    sigma_daily = ret.ewm(span=60, adjust=False, min_periods=60).std()
    sigma_ann = sigma_daily * np.sqrt(252.0)
    out = pd.DataFrame(index=close.index)
    for horizon in (1, 21, 63, 126, 252):
        denom = sigma_ann * np.sqrt(horizon / 252.0)
        out[f"return_{horizon}"] = (close / close.shift(horizon) - 1.0) / denom
    price_std = close.rolling(63, min_periods=63).std()
    for short, long in ((8, 24), (16, 48), (32, 96)):
        fast = close.ewm(alpha=1.0 / short, adjust=False).mean()
        slow = close.ewm(alpha=1.0 / long, adjust=False).mean()
        q = (fast - slow) / price_std
        out[f"macd_{short}_{long}"] = q / q.rolling(252, min_periods=252).std()
    out["sigma_ann"] = sigma_ann
    out["next_return"] = close.shift(-1) / close - 1.0
    out["next_day"] = pd.Series(close.index, index=close.index).shift(-1)
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    return out


def valid_sample_days(features: pd.DataFrame, lookback: int = LOOKBACK,
                      require_label: bool = True) -> list[int]:
    """Index days with a complete trailing window and a following trading day.

The execution strategy never checks a future return when selecting a signal.
"""
    values = features.loc[:, list(FEATURE_NAMES)].to_numpy(dtype=np.float32)
    sigma = features["sigma_ann"].to_numpy(dtype=np.float64)
    next_ret = features["next_return"].to_numpy(dtype=np.float64)
    valid = np.isfinite(values).all(axis=1) & np.isfinite(sigma) & (sigma > 0)
    return [i for i in range(lookback - 1, len(features) - 1)
            if valid[i - lookback + 1:i + 1].all()
            and pd.notna(features.iloc[i]["next_day"])
            and (not require_label or np.isfinite(next_ret[i]))]


def make_network(input_size: int = len(FEATURE_NAMES), hidden_size: int = 20):
    import torch
    from torch import nn

    class MomentumLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.lstm = nn.LSTM(input_size=input_size, hidden_size=hidden_size, batch_first=True)
            self.output = nn.Linear(hidden_size, 1)

        def forward(self, x):
            hidden, _ = self.lstm(x)
            return torch.tanh(self.output(hidden[:, -1, :])).squeeze(-1)

    return MomentumLSTM()


@lru_cache(maxsize=4)
def load_network(path: str):
    import torch

    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if tuple(checkpoint["feature_names"]) != FEATURE_NAMES:
        raise ValueError("model feature schema differs from this strategy version")
    model = make_network(hidden_size=int(checkpoint["hidden_size"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model, checkpoint


def default_model_path() -> Path:
    return Path(__file__).resolve().parents[2] / "models" / "dmn_paper.pt"
