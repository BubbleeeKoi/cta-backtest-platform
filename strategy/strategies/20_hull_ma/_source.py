# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'SHFE.rb2405'
HMA_PERIOD = 20
KLINE_DURATION = 15 * 60
VOLUME = 1
DATA_LENGTH = 300

def calc_wma(series, period):
    pass
    weights = np.arange(1, period + 1, dtype=float)
    wma = series.rolling(window=period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)
    return wma

def calc_hma(close, period):
    pass
    half_period = max(int(period // 2), 2)
    sqrt_period = max(int(np.sqrt(period)), 2)
    wma_half = calc_wma(close, half_period)
    wma_full = calc_wma(close, period)
    raw = 2.0 * wma_half - wma_full
    hma = calc_wma(raw, sqrt_period)
    return hma

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
                hma = calc_hma(close, HMA_PERIOD)
                hma_now = hma.iloc[-1]
                hma_prev = hma.iloc[-2]
                hma_pp = hma.iloc[-3]
                hma_rising = hma_now > hma_prev
                hma_was_falling = hma_prev < hma_pp
                signal_long = hma_rising and hma_was_falling
                signal_short = not hma_rising and hma_prev > hma_pp
                curr_close = close.iloc[-1]
                pass
                if signal_long:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif signal_short:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif not hma_rising:
                    target_pos.set_target_volume(0)
                    pass
                elif hma_rising:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
