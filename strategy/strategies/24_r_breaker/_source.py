# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from datetime import datetime
SYMBOL = 'CFFEX.IF2406'
DAY_DURATION = 86400
TRADE_DURATION = 5 * 60
VOLUME = 1
CLOSE_HOUR = 14
CLOSE_MINUTE = 55
DATA_LENGTH = 10
TRADE_LENGTH = 300

def calc_rbreaker_levels(prev_high, prev_low, prev_close):
    pass
    pivot = (prev_high + prev_low + prev_close) / 3.0
    bbreak = prev_high + 2 * (pivot - prev_low)
    ssetup = pivot + (prev_high - prev_low)
    senter = 2 * pivot - prev_low
    benter = 2 * pivot - prev_high
    bsetup = pivot - (prev_high - prev_low)
    sbreak = prev_low - 2 * (prev_high - pivot)
    return {'pivot': pivot, 'bbreak': bbreak, 'ssetup': ssetup, 'senter': senter, 'benter': benter, 'bsetup': bsetup, 'sbreak': sbreak}

def program(api):
    api = api
    pass
    day_klines = api.get_kline_serial(SYMBOL, DAY_DURATION, data_length=DATA_LENGTH)
    trade_klines = api.get_kline_serial(SYMBOL, TRADE_DURATION, data_length=TRADE_LENGTH)
    account = api.get_account()
    target_pos = TargetPosTask(api, SYMBOL)
    levels = None
    has_touched_ssetup = False
    has_touched_bsetup = False
    today_date = None
    try:
        while True:
            yield None
            if api.is_changing(day_klines.iloc[-1], 'datetime'):
                prev = day_klines.iloc[-2]
                levels = calc_rbreaker_levels(prev['high'], prev['low'], prev['close'])
                has_touched_ssetup = False
                has_touched_bsetup = False
                pass
                pass
                pass
                pass
            if api.is_changing(trade_klines.iloc[-1], 'datetime') and levels is not None:
                curr_close = trade_klines['close'].iloc[-1]
                curr_high = trade_klines['high'].iloc[-1]
                curr_low = trade_klines['low'].iloc[-1]
                prev_close = trade_klines['close'].iloc[-2]
                ts_ns = trade_klines.iloc[-1]['datetime']
                dt_now = pd.Timestamp(ts_ns)
                hour_now = dt_now.hour
                min_now = dt_now.minute
                if hour_now > CLOSE_HOUR or (hour_now == CLOSE_HOUR and min_now >= CLOSE_MINUTE):
                    target_pos.set_target_volume(0)
                    pass
                    continue
                if curr_high >= levels['ssetup']:
                    has_touched_ssetup = True
                if curr_low <= levels['bsetup']:
                    has_touched_bsetup = True
                pass
                if curr_close > levels['bbreak'] and prev_close <= levels['bbreak']:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif curr_close < levels['sbreak'] and prev_close >= levels['sbreak']:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif has_touched_ssetup and curr_close < levels['senter'] and (prev_close >= levels['senter']):
                    target_pos.set_target_volume(-VOLUME)
                    pass
                    has_touched_ssetup = False
                elif has_touched_bsetup and curr_close > levels['benter'] and (prev_close <= levels['benter']):
                    target_pos.set_target_volume(VOLUME)
                    pass
                    has_touched_bsetup = False
    finally:
        api.close()
        pass
