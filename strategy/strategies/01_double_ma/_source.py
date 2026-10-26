# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, crossup, crossdown
SYMBOL = 'SHFE.rb2501'
SHORT_PERIOD = 5
LONG_PERIOD = 20
KLINE_DUR = 60 * 60
VOLUME = 1

def program(api):
    pass
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=LONG_PERIOD + 10)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        ma_short = ma(klines.close, SHORT_PERIOD)
        ma_long = ma(klines.close, LONG_PERIOD)
        is_golden_cross = crossup(ma_short, ma_long).iloc[-1]
        is_death_cross = crossdown(ma_short, ma_long).iloc[-1]
        pass
        if is_golden_cross:
            pass
            target_pos.set_target_volume(VOLUME)
        elif is_death_cross:
            pass
            target_pos.set_target_volume(-VOLUME)
    api.close()
