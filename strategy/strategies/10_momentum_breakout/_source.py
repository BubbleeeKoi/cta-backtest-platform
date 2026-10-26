# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma
SYMBOL = 'SHFE.rb2506'
MOMENTUM_N = 20
THRESHOLD = 2.0
EXIT_THRESHOLD = 0.5
FILTER_N = 60
USE_MA_FILTER = True
VOLUME = 1
KLINE_DURATION = 3600
DATA_LENGTH = 300

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    pass
    pass
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            if api.is_changing(klines):
                close = klines['close']
                close_cur = close.iloc[-2]
                close_n_ago = close.iloc[-2 - MOMENTUM_N]
                if close_n_ago == 0:
                    continue
                momentum = (close_cur - close_n_ago) / close_n_ago * 100.0
                ma_filter = ma(close, FILTER_N)
                ma_cur = ma_filter.iloc[-2]
                price_above_ma = close_cur > ma_cur
                price_below_ma = close_cur < ma_cur
                pass
                position = api.get_position(SYMBOL)
                volume_long = position.volume_long
                volume_short = position.volume_short
                if volume_long > 0:
                    if momentum < EXIT_THRESHOLD:
                        target_pos.set_target_volume(0)
                        pass
                        continue
                if volume_short > 0:
                    if momentum > -EXIT_THRESHOLD:
                        target_pos.set_target_volume(0)
                        pass
                        continue
                can_go_long = not USE_MA_FILTER or price_above_ma
                can_go_short = not USE_MA_FILTER or price_below_ma
                if momentum > THRESHOLD and can_go_long and (volume_long == 0):
                    if volume_short > 0:
                        target_pos.set_target_volume(0)
                        pass
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif momentum < -THRESHOLD and can_go_short and (volume_short == 0):
                    if volume_long > 0:
                        target_pos.set_target_volume(0)
                        pass
                    target_pos.set_target_volume(-VOLUME)
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
