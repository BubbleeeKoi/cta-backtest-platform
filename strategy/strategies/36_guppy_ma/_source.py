# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
from .._source_compat import MA
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 15 * 60
SHORT_PERIODS = [3, 5, 8, 10, 12, 15]
LONG_PERIODS = [30, 35, 40, 45, 50, 60]
STOP_LOSS = 0.03

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < 60:
                continue
            short_ma = []
            for p in SHORT_PERIODS:
                ma = MA(klines, p)
                short_ma.append(ma.iloc[-1])
            short_avg = np.mean(short_ma)
            long_ma = []
            for p in LONG_PERIODS:
                ma = MA(klines, p)
                long_ma.append(ma.iloc[-1])
            long_avg = np.mean(long_ma)
            current_price = klines['close'].iloc[-1]
            pass
            if position == 0:
                if short_avg > long_avg:
                    position = 1
                    entry_price = current_price
                    pass
            elif position == 1:
                if short_avg < long_avg:
                    pass
                    position = 0
                elif current_price < entry_price * (1 - STOP_LOSS):
                    pass
                    position = 0
    api.close()
