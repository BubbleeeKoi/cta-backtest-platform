# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma
import pandas as pd
import numpy as np
SYMBOL = 'SHFE.ru2506'
CCI_N = 14
LEVEL1 = 100
LEVEL2 = 200
VOLUME = 1
KLINE_DURATION = 3600
DATA_LENGTH = 200

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    pass
    pass

    def calc_cci(klines, n=14):
        pass
        high = klines['high']
        low = klines['low']
        close = klines['close']
        tp = (high + low + close) / 3.0
        tp_ma = ma(tp, n)
        md = tp.rolling(window=n).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
        cci = (tp - tp_ma) / (0.015 * md.replace(0, np.nan))
        cci = cci.fillna(0)
        return cci
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            if api.is_changing(klines):
                cci = calc_cci(klines, n=CCI_N)
                cci_cur = cci.iloc[-2]
                cci_prev = cci.iloc[-3]
                pass
                cross_up_200 = cci_prev <= LEVEL2 and cci_cur > LEVEL2
                cross_down_200 = cci_prev >= -LEVEL2 and cci_cur < -LEVEL2
                long_exit = cci_prev >= LEVEL1 and cci_cur < LEVEL1
                short_exit = cci_prev <= -LEVEL1 and cci_cur > -LEVEL1
                position = api.get_position(SYMBOL)
                volume_long = position.volume_long
                volume_short = position.volume_short
                if long_exit and volume_long > 0:
                    target_pos.set_target_volume(0)
                    pass
                if short_exit and volume_short > 0:
                    target_pos.set_target_volume(0)
                    pass
                if cross_up_200:
                    if volume_short > 0:
                        target_pos.set_target_volume(0)
                        pass
                    if volume_long == 0:
                        target_pos.set_target_volume(VOLUME)
                        pass
                if cross_down_200:
                    if volume_long > 0:
                        target_pos.set_target_volume(0)
                        pass
                    if volume_short == 0:
                        target_pos.set_target_volume(-VOLUME)
                        pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
