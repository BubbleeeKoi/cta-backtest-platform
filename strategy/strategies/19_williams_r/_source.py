# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, hhv, llv
SYMBOL = 'SHFE.cu2405'
WR_PERIOD = 14
OVERBOUGHT_LINE = -20
OVERSOLD_LINE = -80
MA_PERIOD = 20
KLINE_DURATION = 5 * 60
VOLUME = 1
DATA_LENGTH = 300

def calc_williams_r(high, low, close, period):
    pass
    highest_high = hhv(high, period)
    lowest_low = llv(low, period)
    price_range = highest_high - lowest_low
    price_range = price_range.replace(0, np.nan)
    wr = (highest_high - close) / price_range * -100
    return wr

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    account = api.get_account()
    target_pos = TargetPosTask(api, SYMBOL)
    try:
        while True:
            yield None
            if api.is_changing(klines.iloc[-1], 'datetime'):
                high = klines['high']
                low = klines['low']
                close = klines['close']
                wr = calc_williams_r(high, low, close, WR_PERIOD)
                wr_now = wr.iloc[-1]
                wr_prev = wr.iloc[-2]
                if MA_PERIOD > 0:
                    ma_line = ma(close, MA_PERIOD)
                    ma_now = ma_line.iloc[-1]
                    ma_prev = ma_line.iloc[-2]
                    trend_up = ma_now > ma_prev
                else:
                    trend_up = True
                pass
                cross_out_oversold = wr_prev < OVERSOLD_LINE and wr_now >= OVERSOLD_LINE
                cross_out_overbought = wr_prev > OVERBOUGHT_LINE and wr_now <= OVERBOUGHT_LINE
                enter_overbought = wr_prev <= OVERBOUGHT_LINE and wr_now > OVERBOUGHT_LINE
                enter_oversold = wr_prev >= OVERSOLD_LINE and wr_now < OVERSOLD_LINE
                if cross_out_oversold and trend_up:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif cross_out_overbought and (not trend_up):
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif enter_overbought:
                    target_pos.set_target_volume(0)
                    pass
                elif enter_oversold:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
