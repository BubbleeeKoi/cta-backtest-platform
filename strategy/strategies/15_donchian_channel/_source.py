# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'SHFE.rb2501'
N_ENTER = 20
N_EXIT = 10
KLINE_DUR = 86400
VOLUME = 1

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=N_ENTER + 5)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        high_enter = klines.high.iloc[-(N_ENTER + 1):-1].max()
        low_enter = klines.low.iloc[-(N_ENTER + 1):-1].min()
        high_exit = klines.high.iloc[-(N_EXIT + 1):-1].max()
        low_exit = klines.low.iloc[-(N_EXIT + 1):-1].min()
        last_close = klines.close.iloc[-2]
        pass
        if last_close > high_enter:
            pass
            target_pos.set_target_volume(VOLUME)
        elif last_close < low_enter:
            pass
            target_pos.set_target_volume(-VOLUME)
        elif last_close < low_exit:
            pass
            target_pos.set_target_volume(0)
        elif last_close > high_exit:
            pass
            target_pos.set_target_volume(0)
    api.close()
