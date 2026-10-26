# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import crossup, crossdown
SYMBOL = 'SHFE.rb2405'
AROON_PERIOD = 25
AROON_THRESH = 70
KLINE_DURATION = 5 * 60
VOLUME = 1
DATA_LENGTH = 200

def calc_aroon(high_series, low_series, period):
    pass
    n = len(high_series)
    aroon_up = np.full(n, np.nan)
    aroon_down = np.full(n, np.nan)
    for i in range(period, n):
        high_window = high_series.iloc[i - period:i + 1].values
        low_window = low_series.iloc[i - period:i + 1].values
        high_idx = np.argmax(high_window)
        low_idx = np.argmin(low_window)
        periods_since_high = period - high_idx
        periods_since_low = period - low_idx
        aroon_up[i] = (period - periods_since_high) / period * 100
        aroon_down[i] = (period - periods_since_low) / period * 100
    return (aroon_up, aroon_down)

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
                aroon_up, aroon_down = calc_aroon(high, low, AROON_PERIOD)
                import pandas as pd
                aroon_up_s = pd.Series(aroon_up, name='aroon_up')
                aroon_down_s = pd.Series(aroon_down, name='aroon_down')
                cross_up_signal = crossup(aroon_up_s, aroon_down_s)
                cross_down_signal = crossup(aroon_down_s, aroon_up_s)
                last_aroon_up = aroon_up[-1]
                last_aroon_down = aroon_down[-1]
                last_cross_up = bool(cross_up_signal.iloc[-1])
                last_cross_down = bool(cross_down_signal.iloc[-1])
                pass
                if last_cross_up and last_aroon_up > AROON_THRESH:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif last_cross_down and last_aroon_down > AROON_THRESH:
                    target_pos.set_target_volume(-VOLUME)
                    pass
    finally:
        api.close()
        pass
