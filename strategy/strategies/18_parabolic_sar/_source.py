# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'SHFE.rb2405'
INIT_AF = 0.02
STEP = 0.02
MAX_AF = 0.2
KLINE_DURATION = 15 * 60
VOLUME = 1
DATA_LENGTH = 300

def calc_parabolic_sar(high, low, close, init_af=0.02, step=0.02, max_af=0.2):
    pass
    n = len(close)
    sar = np.zeros(n)
    trend = np.zeros(n)
    high_arr = high.values
    low_arr = low.values
    close_arr = close.values
    if close_arr[1] > close_arr[0]:
        trend[0] = 1
        sar[0] = low_arr[0]
        ep = high_arr[0]
    else:
        trend[0] = -1
        sar[0] = high_arr[0]
        ep = low_arr[0]
    af = init_af
    for i in range(1, n):
        prev_trend = trend[i - 1]
        prev_sar = sar[i - 1]
        if prev_trend == 1:
            new_sar = prev_sar + af * (ep - prev_sar)
            if i >= 2:
                new_sar = min(new_sar, low_arr[i - 1], low_arr[i - 2])
            else:
                new_sar = min(new_sar, low_arr[i - 1])
            if low_arr[i] < new_sar:
                trend[i] = -1
                sar[i] = ep
                ep = low_arr[i]
                af = init_af
            else:
                trend[i] = 1
                sar[i] = new_sar
                if high_arr[i] > ep:
                    ep = high_arr[i]
                    af = min(af + step, max_af)
        else:
            new_sar = prev_sar + af * (ep - prev_sar)
            if i >= 2:
                new_sar = max(new_sar, high_arr[i - 1], high_arr[i - 2])
            else:
                new_sar = max(new_sar, high_arr[i - 1])
            if high_arr[i] > new_sar:
                trend[i] = 1
                sar[i] = ep
                ep = high_arr[i]
                af = init_af
            else:
                trend[i] = -1
                sar[i] = new_sar
                if low_arr[i] < ep:
                    ep = low_arr[i]
                    af = min(af + step, max_af)
    return (sar, trend)

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
                high = klines['high']
                low = klines['low']
                close = klines['close']
                sar, trend = calc_parabolic_sar(high, low, close, INIT_AF, STEP, MAX_AF)
                curr_sar = sar[-1]
                curr_trend = trend[-1]
                prev_trend = trend[-2]
                curr_close = close.iloc[-1]
                pass
                if curr_trend == 1 and prev_trend == -1:
                    pass
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif curr_trend == -1 and prev_trend == 1:
                    pass
                    target_pos.set_target_volume(-VOLUME)
                    pass
    finally:
        api.close()
        pass
