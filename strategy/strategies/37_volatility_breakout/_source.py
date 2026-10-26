# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
from .._source_compat import ATR
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 60 * 60
ATR_PERIOD = 14
CHANNEL_MULTI = 2.5
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=50)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < ATR_PERIOD + 10:
                continue
            atr = ATR(klines, ATR_PERIOD).iloc[-1]
            current_price = klines['close'].iloc[-1]
            ma20 = klines['close'].iloc[-20:].mean()
            upper = ma20 + atr * CHANNEL_MULTI
            lower = ma20 - atr * CHANNEL_MULTI
            pass
            if position == 0:
                if current_price > upper:
                    position = 1
                    entry_price = current_price
                    pass
                elif current_price < lower:
                    position = -1
                    entry_price = current_price
                    pass
            elif position == 1:
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct < -STOP_LOSS:
                    pass
                    position = 0
                elif pnl_pct > TAKE_PROFIT:
                    pass
                    position = 0
                elif current_price < ma20:
                    pass
                    position = 0
            elif position == -1:
                pnl_pct = (entry_price - current_price) / entry_price
                if pnl_pct < -STOP_LOSS:
                    pass
                    position = 0
                elif pnl_pct > TAKE_PROFIT:
                    pass
                    position = 0
                elif current_price > ma20:
                    pass
                    position = 0
    api.close()
