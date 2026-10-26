# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import hhv, llv, ma
import numpy as np
SYMBOL = 'DCE.m2506'
KDJ_N = 9
KDJ_M1 = 3
KDJ_M2 = 3
OVERBUY = 80
OVERSELL = 20
VOLUME = 1
KLINE_DURATION = 1800
DATA_LENGTH = 300

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    pass
    pass

    def calc_kdj(klines, n=9, m1=3, m2=3):
        pass
        high = klines['high']
        low = klines['low']
        close = klines['close']
        hh = hhv(high, n)
        ll = llv(low, n)
        denominator = hh - ll
        denominator = denominator.replace(0, 1)
        rsv = (close - ll) / denominator * 100
        k_values = []
        k_prev = 50.0
        for rsv_val in rsv:
            if np.isnan(rsv_val):
                k_values.append(np.nan)
            else:
                k_cur = k_prev * (1 - 1.0 / m1) + rsv_val * (1.0 / m1)
                k_values.append(k_cur)
                k_prev = k_cur
        import pandas as pd
        k_series = pd.Series(k_values, index=close.index)
        d_values = []
        d_prev = 50.0
        for k_val in k_series:
            if np.isnan(k_val):
                d_values.append(np.nan)
            else:
                d_cur = d_prev * (1 - 1.0 / m2) + k_val * (1.0 / m2)
                d_values.append(d_cur)
                d_prev = d_cur
        d_series = pd.Series(d_values, index=close.index)
        j_series = 3 * k_series - 2 * d_series
        return (k_series, d_series, j_series)
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            if api.is_changing(klines):
                k, d, j = calc_kdj(klines, n=KDJ_N, m1=KDJ_M1, m2=KDJ_M2)
                k_cur = k.iloc[-2]
                d_cur = d.iloc[-2]
                j_cur = j.iloc[-2]
                k_prev = k.iloc[-3]
                d_prev = d.iloc[-3]
                pass
                golden_cross = k_prev < d_prev and k_cur > d_cur
                death_cross = k_prev > d_prev and k_cur < d_cur
                position = api.get_position(SYMBOL)
                volume_long = position.volume_long
                volume_short = position.volume_short
                if golden_cross and k_cur < 50:
                    if volume_short > 0:
                        target_pos.set_target_volume(0)
                        pass
                    if volume_long == 0:
                        target_pos.set_target_volume(VOLUME)
                        pass
                elif death_cross and k_cur > 50:
                    if volume_long > 0:
                        target_pos.set_target_volume(0)
                        pass
                    if volume_short == 0:
                        target_pos.set_target_volume(-VOLUME)
                        pass
                if volume_long > 0 and k_cur > OVERBUY:
                    target_pos.set_target_volume(0)
                    pass
                if volume_short > 0 and k_cur < OVERSELL:
                    target_pos.set_target_volume(0)
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
