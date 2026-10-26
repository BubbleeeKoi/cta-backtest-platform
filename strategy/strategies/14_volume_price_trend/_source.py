# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import hhv, llv, ma
SYMBOL = 'SHFE.cu2506'
BREAKOUT_N = 20
EXIT_N = 10
VOL_MA_N = 20
VOL_MULTIPLIER = 1.5
VOLUME = 1
KLINE_DURATION = 86400
DATA_LENGTH = 150

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    pass
    try:
        while True:
            yield None
            if api.is_changing(klines):
                close = klines['close']
                volume = klines['volume']
                high = klines['high']
                low = klines['low']
                channel_high_n = hhv(close, BREAKOUT_N)
                channel_low_n = llv(close, BREAKOUT_N)
                channel_high_exit = hhv(high, EXIT_N)
                channel_low_exit = llv(low, EXIT_N)
                vol_ma = ma(volume, VOL_MA_N)
                close_cur = close.iloc[-2]
                close_prev = close.iloc[-3]
                prev_channel_high = channel_high_n.iloc[-3]
                prev_channel_low = channel_low_n.iloc[-3]
                vol_cur = volume.iloc[-2]
                vol_ma_cur = vol_ma.iloc[-2]
                if vol_ma_cur > 0:
                    vol_ratio = vol_cur / vol_ma_cur
                else:
                    vol_ratio = 0
                exit_high = channel_high_exit.iloc[-2]
                exit_low = channel_low_exit.iloc[-2]
                pass
                is_big_volume = vol_ratio >= VOL_MULTIPLIER
                if close_cur < exit_low:
                    target_pos.set_target_volume(0)
                    pass
                elif close_cur > exit_high:
                    target_pos.set_target_volume(0)
                    pass
                elif close_cur > prev_channel_high and is_big_volume:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif close_cur < prev_channel_low and is_big_volume:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif not is_big_volume and (close_cur > prev_channel_high or close_cur < prev_channel_low):
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
