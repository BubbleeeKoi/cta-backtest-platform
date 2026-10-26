# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
from .._source_compat import BOLL
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 15 * 60
BOLL_PERIOD = 20
BOLL_STD = 2.0
STOP_LOSS = 0.015

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=BOLL_PERIOD + 20)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < BOLL_PERIOD + 5:
                continue
            boll = BOLL(klines, BOLL_PERIOD, BOLL_STD)
            upper = boll['upper'].iloc[-1]
            middle = boll['middle'].iloc[-1]
            lower = boll['lower'].iloc[-1]
            current_price = klines['close'].iloc[-1]
            pass
            if position == 0:
                if current_price <= lower:
                    position = 1
                    entry_price = current_price
                    pass
                elif current_price >= upper:
                    position = -1
                    entry_price = current_price
                    pass
            elif position == 1:
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct < -STOP_LOSS:
                    pass
                    position = 0
                elif current_price >= middle:
                    pass
                    position = 0
            elif position == -1:
                pnl_pct = (entry_price - current_price) / entry_price
                if pnl_pct < -STOP_LOSS:
                    pass
                    position = 0
                elif current_price <= middle:
                    pass
                    position = 0
    api.close()
