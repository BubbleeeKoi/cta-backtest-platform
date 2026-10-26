# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 30 * 60
VOL_MA_PERIOD = 20
VOL_MULTI = 1.5
STOP_LOSS = 0.02
TAKE_PROFIT = 0.05

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=50)
    position = 0
    entry_price = 0
    high_price = 0
    low_price = float('inf')
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < VOL_MA_PERIOD + 10:
                continue
            current_price = klines['close'].iloc[-1]
            current_vol = klines['volume'].iloc[-1]
            vol_ma = klines['volume'].iloc[-VOL_MA_PERIOD:].mean()
            high_20 = klines['high'].iloc[-20:].max()
            low_20 = klines['low'].iloc[-20:].min()
            if position == 0:
                if current_price > high_20 and current_vol > vol_ma * VOL_MULTI:
                    position = 1
                    entry_price = current_price
                    high_price = high_20
                    pass
                elif current_price < low_20 and current_vol > vol_ma * VOL_MULTI:
                    position = -1
                    entry_price = current_price
                    low_price = low_20
                    pass
            elif position == 1:
                pnl_pct = (current_price - entry_price) / entry_price
                if pnl_pct < -STOP_LOSS:
                    pass
                    position = 0
                elif pnl_pct > TAKE_PROFIT:
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
    api.close()
