# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, crossup, crossdown
SYMBOL = 'SHFE.au2506'
DAY_MA_N = 20
HOUR_MA_N = 20
MIN15_FAST_N = 5
MIN15_SLOW_N = 20
VOLUME = 1

def program(api):
    api = api
    klines_day = api.get_kline_serial(SYMBOL, 86400, data_length=DAY_MA_N + 5)
    klines_hour = api.get_kline_serial(SYMBOL, 3600, data_length=HOUR_MA_N + 5)
    klines_15m = api.get_kline_serial(SYMBOL, 900, data_length=MIN15_SLOW_N + 5)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not (api.is_changing(klines_day) or api.is_changing(klines_hour) or api.is_changing(klines_15m)):
            continue
        ma_day = ma(klines_day.close, DAY_MA_N)
        day_trend_up = klines_day.close.iloc[-2] > ma_day.iloc[-2]
        day_trend_down = klines_day.close.iloc[-2] < ma_day.iloc[-2]
        ma_hour = ma(klines_hour.close, HOUR_MA_N)
        hour_trend_up = klines_hour.close.iloc[-2] > ma_hour.iloc[-2]
        hour_trend_down = klines_hour.close.iloc[-2] < ma_hour.iloc[-2]
        ma_fast = ma(klines_15m.close, MIN15_FAST_N)
        ma_slow = ma(klines_15m.close, MIN15_SLOW_N)
        cross_up = bool(crossup(ma_fast, ma_slow).iloc[-2])
        cross_down = bool(crossdown(ma_fast, ma_slow).iloc[-2])
        pass
        if day_trend_up and hour_trend_up and cross_up:
            pass
            target_pos.set_target_volume(VOLUME)
        elif day_trend_down and hour_trend_down and cross_down:
            pass
            target_pos.set_target_volume(-VOLUME)
        elif cross_down:
            pass
            target_pos.set_target_volume(0)
        elif cross_up:
            pass
            target_pos.set_target_volume(0)
    api.close()
