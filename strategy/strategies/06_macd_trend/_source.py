# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ema, crossup, crossdown
SYMBOL = 'SHFE.cu2506'
FAST_PERIOD = 12
SLOW_PERIOD = 26
SIGNAL_PERIOD = 9
VOLUME = 1
KLINE_DURATION = 3600
DATA_LENGTH = 300

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    try:
        while True:
            yield None
            if not api.is_changing(klines):
                continue
            close = klines['close']
            ema_fast = ema(close, FAST_PERIOD)
            ema_slow = ema(close, SLOW_PERIOD)
            dif = ema_fast - ema_slow
            dea = ema(dif, SIGNAL_PERIOD)
            macd_bar = (dif - dea) * 2
            is_golden = bool(crossup(dif, dea).iloc[-2])
            is_death = bool(crossdown(dif, dea).iloc[-2])
            pass
            if is_golden:
                pass
                target_pos.set_target_volume(VOLUME)
            elif is_death:
                pass
                target_pos.set_target_volume(-VOLUME)
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
