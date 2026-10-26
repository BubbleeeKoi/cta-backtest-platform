# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'CFFEX.IF2406'
DAY_DURATION = 86400
TRADE_DURATION = 5 * 60
TOUCH_RANGE = 5.0
VOLUME = 1
DATA_LENGTH = 50
TRADE_LENGTH = 500

def calc_pivot_points(prev_high, prev_low, prev_close):
    pass
    pp = (prev_high + prev_low + prev_close) / 3.0
    r1 = 2.0 * pp - prev_low
    r2 = pp + (prev_high - prev_low)
    s1 = 2.0 * pp - prev_high
    s2 = pp - (prev_high - prev_low)
    return (pp, r1, r2, s1, s2)

def program(api):
    api = api
    pass
    day_klines = api.get_kline_serial(SYMBOL, DAY_DURATION, data_length=DATA_LENGTH)
    trade_klines = api.get_kline_serial(SYMBOL, TRADE_DURATION, data_length=TRADE_LENGTH)
    account = api.get_account()
    target_pos = TargetPosTask(api, SYMBOL)
    pp = r1 = r2 = s1 = s2 = None
    try:
        while True:
            yield None
            if api.is_changing(day_klines.iloc[-1], 'datetime'):
                prev_day = day_klines.iloc[-2]
                pp, r1, r2, s1, s2 = calc_pivot_points(prev_day['high'], prev_day['low'], prev_day['close'])
                pass
            if api.is_changing(trade_klines.iloc[-1], 'datetime') and pp is not None:
                curr_close = trade_klines['close'].iloc[-1]
                prev_close = trade_klines['close'].iloc[-2]
                cross_pp_up = prev_close < pp and curr_close >= pp
                cross_pp_down = prev_close > pp and curr_close <= pp
                touch_s1 = abs(curr_close - s1) <= TOUCH_RANGE and curr_close < pp
                touch_r1 = abs(curr_close - r1) <= TOUCH_RANGE and curr_close > pp
                pass
                if cross_pp_up:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif cross_pp_down:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif touch_s1:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif touch_r1:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif curr_close >= r1:
                    target_pos.set_target_volume(0)
                    pass
                elif curr_close <= s1:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
