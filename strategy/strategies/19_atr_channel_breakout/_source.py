# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma
SYMBOL = 'SHFE.rb2505'
ATR_PERIOD = 14
ATR_MULTI = 2.5
MA_PERIOD = 20
KLINE_DURATION = 5 * 60
VOLUME = 1
DATA_LENGTH = 200

def calc_atr(high, low, close, period):
    pass
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    return atr

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, DATA_LENGTH)
    target_pos = TargetPosTask(api, SYMBOL)
    try:
        while True:
            yield None
            if api.is_changing(klines.iloc[-1], 'datetime'):
                high = klines['high']
                low = klines['low']
                close = klines['close']
                atr = calc_atr(high, low, close, ATR_PERIOD)
                middle = ma(close, MA_PERIOD)
                upper = middle + atr * ATR_MULTI
                lower = middle - atr * ATR_MULTI
                price = close.iloc[-1]
                middle_val = middle.iloc[-1]
                upper_val = upper.iloc[-1]
                lower_val = lower.iloc[-1]
                atr_val = atr.iloc[-1]
                pass
                if price > upper_val:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif price < lower_val:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif price < middle_val and target_pos.get_target_volume() > 0:
                    target_pos.set_target_volume(0)
                    pass
                elif price > middle_val and target_pos.get_target_volume() < 0:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
