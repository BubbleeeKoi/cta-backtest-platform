# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, ema, crossup, crossdown
import pandas as pd
import numpy as np
SYMBOL = 'SHFE.au2506'
MA_FAST = 10
MA_SLOW = 30
ATR_N = 14
ATR_MULTIPLIER = 2.0
VOLUME = 1
KLINE_DURATION = 3600
DATA_LENGTH = 300

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    pass
    pass
    long_stop_price = 0.0
    short_stop_price = float('inf')

    def calc_atr(klines, n=14):
        pass
        high = klines['high']
        low = klines['low']
        close = klines['close']
        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = ema(tr, n)
        return atr
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            position = api.get_position(SYMBOL)
            if api.is_changing(quote):
                current_price = quote.last_price
                if position.volume_long > 0 and long_stop_price > 0:
                    if current_price < long_stop_price:
                        triggered_stop_price = long_stop_price
                        target_pos.set_target_volume(0)
                        long_stop_price = 0.0
                        pass
                if position.volume_short > 0 and short_stop_price < float('inf'):
                    if current_price > short_stop_price:
                        triggered_stop_price = short_stop_price
                        target_pos.set_target_volume(0)
                        short_stop_price = float('inf')
                        pass
            if api.is_changing(klines):
                close = klines['close']
                ma_fast = ma(close, MA_FAST)
                ma_slow = ma(close, MA_SLOW)
                atr = calc_atr(klines, n=ATR_N)
                close_cur = close.iloc[-2]
                atr_cur = atr.iloc[-2]
                ma_fast_cur = ma_fast.iloc[-2]
                ma_slow_cur = ma_slow.iloc[-2]
                is_golden = bool(crossup(ma_fast, ma_slow).iloc[-2])
                is_death = bool(crossdown(ma_fast, ma_slow).iloc[-2])
                atr_stop_dist = ATR_MULTIPLIER * atr_cur
                if position.volume_long > 0:
                    new_long_stop = close_cur - atr_stop_dist
                    long_stop_price = max(long_stop_price, new_long_stop)
                    pass
                if position.volume_short > 0:
                    new_short_stop = close_cur + atr_stop_dist
                    short_stop_price = min(short_stop_price, new_short_stop)
                    pass
                pass
                if is_golden:
                    if position.volume_short > 0:
                        target_pos.set_target_volume(0)
                        short_stop_price = float('inf')
                        pass
                    if position.volume_long == 0:
                        target_pos.set_target_volume(VOLUME)
                        long_stop_price = close_cur - atr_stop_dist
                        pass
                elif is_death:
                    if position.volume_long > 0:
                        target_pos.set_target_volume(0)
                        long_stop_price = 0.0
                        pass
                    if position.volume_short == 0:
                        target_pos.set_target_volume(-VOLUME)
                        short_stop_price = close_cur + atr_stop_dist
                        pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
