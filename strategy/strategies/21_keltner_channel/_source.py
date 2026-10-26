# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ema
SYMBOL = 'SHFE.rb2405'
EMA_PERIOD = 20
ATR_PERIOD = 10
ATR_MULT = 2.0
KLINE_DURATION = 15 * 60
VOLUME = 1
DATA_LENGTH = 300

def calc_atr(high, low, close, period):
    pass
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr

def calc_keltner_channel(close, high, low, ema_period, atr_period, atr_mult):
    pass
    middle = ema(close, ema_period)
    atr = calc_atr(high, low, close, atr_period)
    upper = middle + atr_mult * atr
    lower = middle - atr_mult * atr
    return (middle, upper, lower)

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    account = api.get_account()
    target_pos = TargetPosTask(api, SYMBOL)
    try:
        while True:
            yield None
            if api.is_changing(klines.iloc[-1], 'datetime'):
                close = klines['close']
                high = klines['high']
                low = klines['low']
                middle, upper, lower = calc_keltner_channel(close, high, low, EMA_PERIOD, ATR_PERIOD, ATR_MULT)
                close_now = close.iloc[-1]
                close_prev = close.iloc[-2]
                upper_now = upper.iloc[-1]
                upper_prev = upper.iloc[-2]
                lower_now = lower.iloc[-1]
                lower_prev = lower.iloc[-2]
                mid_now = middle.iloc[-1]
                breakout_up = close_prev <= upper_prev and close_now > upper_now
                breakout_down = close_prev >= lower_prev and close_now < lower_now
                pass
                if breakout_up:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif breakout_down:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif close_now < mid_now:
                    target_pos.set_target_volume(0)
                    pass
                elif close_now > mid_now:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
