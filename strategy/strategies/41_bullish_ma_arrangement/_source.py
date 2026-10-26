# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 30 * 60
MA_SHORT = 10
MA_MID = 30
MA_LONG = 60
STOP_LOSS = 0.025
TAKE_PROFIT = 0.08

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < MA_LONG + 10:
                continue
            closes = klines['close'].values
            ma_short = np.mean(closes[-MA_SHORT:])
            ma_mid = np.mean(closes[-MA_MID:])
            ma_long = np.mean(closes[-MA_LONG:])
            bullish_arrangement = ma_short > ma_mid > ma_long
            bearish_arrangement = ma_short < ma_mid < ma_long
            if position == 0 and bullish_arrangement:
                if closes[-1] <= ma_mid * 1.01:
                    position = 1
                    entry_price = closes[-1]
                    pass
            elif position == 1 and bearish_arrangement:
                pnl = (closes[-1] - entry_price) / entry_price
                pass
                position = 0
            elif position == 1:
                pnl = (closes[-1] - entry_price) / entry_price
                if pnl <= -STOP_LOSS:
                    pass
                    position = 0
                elif pnl >= TAKE_PROFIT:
                    pass
                    position = 0
