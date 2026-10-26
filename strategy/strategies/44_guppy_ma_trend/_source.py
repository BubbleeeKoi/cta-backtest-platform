# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 15 * 60
SHORT_PERIODS = [3, 5, 8, 10, 12, 15]
LONG_PERIODS = [30, 35, 40, 45, 50, 60]
STOP_LOSS = 0.02
TAKE_PROFIT = 0.04

def calc_ma(closes, period):
    pass
    if len(closes) < period:
        return None
    return np.mean(closes[-period:])

def calc_guppy_group(closes, periods):
    pass
    values = []
    for p in periods:
        ma = calc_ma(closes, p)
        if ma is not None:
            values.append(ma)
    return values

def guppy_trend(closes, short_periods, long_periods):
    pass
    short_group = calc_guppy_group(closes, short_periods)
    long_group = calc_guppy_group(closes, long_periods)
    if not short_group or not long_group:
        return 0
    short_ma = np.mean(short_group)
    long_ma = np.mean(long_group)
    if short_ma > long_ma:
        return 1
    elif short_ma < long_ma:
        return -1
    return 0

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < 70:
                continue
            closes = klines['close'].values
            trend = guppy_trend(closes, SHORT_PERIODS, LONG_PERIODS)
            current_price = closes[-1]
            short_ma_5 = calc_ma(closes, 5)
            short_ma_10 = calc_ma(closes, 10)
            if short_ma_5 and short_ma_10:
                pass
            if position == 0 and trend == 1:
                position = 1
                entry_price = current_price
                pass
            elif position == 0 and trend == -1:
                position = -1
                entry_price = current_price
                pass
            elif position != 0:
                pnl = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
                if pnl <= -STOP_LOSS:
                    pass
                    position = 0
                elif pnl >= TAKE_PROFIT:
                    pass
                    position = 0
