# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 15 * 60
TREND_PERIOD = 50
MOMENTUM_PERIOD = 14
STOP_LOSS = 0.02
TAKE_PROFIT = 0.06

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < TREND_PERIOD + 10:
                continue
            closes = klines['close'].values
            highs = klines['high'].values
            lows = klines['low'].values
            ma = np.mean(closes[-TREND_PERIOD:])
            trend_up = closes[-1] > ma
            momentum = closes[-1] - closes[-MOMENTUM_PERIOD]
            momentum_accelerating = momentum > closes[-MOMENTUM_PERIOD] - closes[-2 * MOMENTUM_PERIOD]
            if position == 0 and trend_up and (momentum > 0) and momentum_accelerating:
                position = 1
                entry_price = closes[-1]
                pass
            elif position == 0 and (not trend_up) and (momentum < 0) and (not momentum_accelerating):
                position = -1
                entry_price = closes[-1]
                pass
            elif position != 0:
                pnl = (closes[-1] - entry_price) / entry_price if position == 1 else (entry_price - closes[-1]) / entry_price
                if pnl <= -STOP_LOSS or pnl >= TAKE_PROFIT:
                    pass
                    position = 0
