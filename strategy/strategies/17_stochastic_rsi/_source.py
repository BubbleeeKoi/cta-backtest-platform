# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, crossup, crossdown
SYMBOL = 'SHFE.au2406'
RSI_PERIOD = 14
STOCH_PERIOD = 14
SMOOTH_K = 3
SMOOTH_D = 3
OVERBOUGHT = 0.8
OVERSOLD = 0.2
KLINE_DURATION = 5 * 60
VOLUME = 1
DATA_LENGTH = 300

def calc_rsi(close_series, period):
    pass
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - 100 / (1 + rs)
    return rsi

def calc_stoch_rsi(rsi_series, stoch_period, smooth_k, smooth_d):
    pass
    rsi_max = rsi_series.rolling(window=stoch_period).max()
    rsi_min = rsi_series.rolling(window=stoch_period).min()
    denom = rsi_max - rsi_min
    stoch_raw = (rsi_series - rsi_min) / denom.replace(0, np.nan)
    stoch_k = stoch_raw.rolling(window=smooth_k).mean()
    stoch_d = stoch_k.rolling(window=smooth_d).mean()
    return (stoch_k, stoch_d)

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
                close = klines['close']
                rsi = calc_rsi(close, RSI_PERIOD)
                stoch_k, stoch_d = calc_stoch_rsi(rsi, STOCH_PERIOD, SMOOTH_K, SMOOTH_D)
                k_now = stoch_k.iloc[-1]
                d_now = stoch_d.iloc[-1]
                rsi_now = rsi.iloc[-1]
                cross_up_sig = crossup(stoch_k, stoch_d)
                cross_down_sig = crossdown(stoch_k, stoch_d)
                last_cross_up = bool(cross_up_sig.iloc[-1])
                last_cross_down = bool(cross_down_sig.iloc[-1])
                pass
                if last_cross_up and k_now < OVERSOLD:
                    target_pos.set_target_volume(VOLUME)
                    pass
                elif last_cross_down and k_now > OVERBOUGHT:
                    target_pos.set_target_volume(-VOLUME)
                    pass
                elif k_now > OVERBOUGHT:
                    target_pos.set_target_volume(0)
                    pass
                elif k_now < OVERSOLD:
                    target_pos.set_target_volume(0)
                    pass
    finally:
        api.close()
        pass
