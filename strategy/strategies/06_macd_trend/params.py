"""Default parameters for the 60-minute MACD trend strategy."""

FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9
VOLUME = 1
KLINE_DURATION = 3600
SESSION_NAME = "全天"

# Native source constant overrides, e.g. {"RSI_PERIOD": 14}.
# FAST_PERIOD/SLOW_PERIOD/SIGNAL_PERIOD above are legacy metadata;
# signal formulas use the original constants in _source.py.
SOURCE_PARAMS = {}
