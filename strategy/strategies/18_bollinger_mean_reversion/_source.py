# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma
SYMBOL = 'SHFE.rb2505'
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
KLINE_DURATION = 5 * 60
VOLUME = 1
DATA_LENGTH = 200

def calc_bollinger_bands(close, period, std_multiplier):
    pass
    middle = ma(close, period)
    std = close.rolling(window=period).std()
    upper = middle + std * std_multiplier
    lower = middle - std * std_multiplier
    return (upper, middle, lower)

def calc_rsi(close, period):
    pass
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - 100 / (1 + rs)
    return rsi

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, DATA_LENGTH)
    target_pos = TargetPosTask(api, SYMBOL)
    try:
        while True:
            yield None
            if api.is_changing(klines.iloc[-1], 'datetime'):
                close = klines['close']
                upper, middle, lower = calc_bollinger_bands(close, BB_PERIOD, BB_STD)
                rsi = calc_rsi(close, RSI_PERIOD)
                price = close.iloc[-1]
                upper_val = upper.iloc[-1]
                middle_val = middle.iloc[-1]
                lower_val = lower.iloc[-1]
                rsi_val = rsi.iloc[-1]
                pass
                if price <= lower_val and rsi_val < RSI_OVERSOLD:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif price >= upper_val and rsi_val > RSI_OVERBOUGHT:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif price >= middle_val and target_pos.get_target_volume() > 0:
                    target_pos.set_target_volume(0)
                    pass
                elif price <= middle_val and target_pos.get_target_volume() < 0:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
