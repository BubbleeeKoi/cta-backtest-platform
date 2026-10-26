# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, std
SYMBOL = 'DCE.m2501'
N_PERIOD = 20
K_TIMES = 2.0
KLINE_DUR = 60 * 60
VOLUME = 1
MIN_BAND_WIDTH = 0.01

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=N_PERIOD + 10)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        close = klines.close
        middle = ma(close, N_PERIOD)
        std_dev = std(close, N_PERIOD)
        upper = middle + K_TIMES * std_dev
        lower = middle - K_TIMES * std_dev
        last_close = close.iloc[-1]
        last_upper = upper.iloc[-1]
        last_lower = lower.iloc[-1]
        last_middle = middle.iloc[-1]
        band_width = (last_upper - last_lower) / last_middle
        pass
        if band_width < MIN_BAND_WIDTH:
            continue
        if last_close > last_upper:
            pass
            target_pos.set_target_volume(VOLUME)
        elif last_close < last_lower:
            pass
            target_pos.set_target_volume(-VOLUME)
        elif last_close < last_middle:
            pass
            target_pos.set_target_volume(0)
        elif last_close > last_middle:
            pass
            target_pos.set_target_volume(0)
    api.close()
