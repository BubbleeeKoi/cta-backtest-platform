# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ema, ma, crossup, crossdown
SYMBOL = 'SHFE.au2406'
TRIX_PERIOD = 12
SIGNAL_PERIOD = 9
KLINE_DURATION = 30 * 60
VOLUME = 1
DATA_LENGTH = 500

def calc_trix(close, period, signal_period):
    pass
    ema1 = ema(close, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    ema3_prev = ema3.shift(1)
    trix = (ema3 - ema3_prev) / ema3_prev * 100
    signal = ma(trix, signal_period)
    return (trix, signal)

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
                trix, signal = calc_trix(close, TRIX_PERIOD, SIGNAL_PERIOD)
                trix_now = trix.iloc[-1]
                signal_now = signal.iloc[-1]
                trix_prev = trix.iloc[-2]
                cross_up_sig = crossup(trix, signal)
                cross_down_sig = crossdown(trix, signal)
                last_cross_up = bool(cross_up_sig.iloc[-1])
                last_cross_down = bool(cross_down_sig.iloc[-1])
                trix_cross_zero_up = trix_prev < 0 and trix_now >= 0
                trix_cross_zero_down = trix_prev > 0 and trix_now <= 0
                pass
                if last_cross_up and trix_now > 0:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif trix_cross_zero_up:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif last_cross_down and trix_now < 0:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif trix_cross_zero_down:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif last_cross_down:
                    target_pos.set_target_volume(0)
                    pass
                elif last_cross_up:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
