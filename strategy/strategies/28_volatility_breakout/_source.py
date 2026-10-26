# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import atr, dx
import numpy as np
SYMBOL = 'INE.sc2501'
KLINE_DUR = 60 * 60
BREAKOUT_PERIOD = 20
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 25
ATR_MULT = 1.5
VOLUME = 1

def calc_adx(high, low, close, period):
    pass
    if len(high) < period + 1:
        return np.nan
    dx_vals = dx(high, low, close, period)
    adx = atr(high, low, close, period)[-1]
    if len(dx_vals) < period or adx == 0:
        return np.nan
    return np.mean(dx_vals[-period:]) / adx * 100

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=BREAKOUT_PERIOD + ATR_PERIOD + ADX_PERIOD + 10)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    position = 0
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        close = klines.close.values
        high = klines.high.values
        low = klines.low.values
        atr_val = atr(high, low, close, ATR_PERIOD)[-1]
        adx_val = calc_adx(high, low, close, ADX_PERIOD)
        highest_high = np.max(close[-BREAKOUT_PERIOD:])
        lowest_low = np.min(close[-BREAKOUT_PERIOD:])
        current_close = close[-1]
        is_breakout_up = current_close > highest_high
        is_breakout_down = current_close < lowest_low
        stop_loss_long = current_close - ATR_MULT * atr_val
        stop_loss_short = current_close + ATR_MULT * atr_val
        signal = 0
        if is_breakout_up and (adx_val is not None and adx_val > ADX_THRESHOLD):
            signal = 1
            pass
        if is_breakout_down and (adx_val is not None and adx_val > ADX_THRESHOLD):
            signal = -1
            pass
        if signal == 1 and position != 1:
            pass
            target_pos.set_target_volume(VOLUME)
            position = 1
        elif signal == -1 and position != -1:
            pass
            target_pos.set_target_volume(-VOLUME)
            position = -1
        if position == 1 and close[-1] < stop_loss_long:
            pass
            target_pos.set_target_volume(0)
            position = 0
        elif position == -1 and close[-1] > stop_loss_short:
            pass
            target_pos.set_target_volume(0)
            position = 0
    api.close()
