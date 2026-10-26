"""Deep Momentum Network strategy based on Lim, Zohren and Roberts (2019)."""

import torch  # Load PyTorch's Windows DLLs before pandas/native framework imports.

from .strategy import Strategy

STRATEGY_NAME = "DMN_LSTM_Sharpe"

__all__ = ["Strategy", "STRATEGY_NAME"]
