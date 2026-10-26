# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqBacktest, TqSim
from .._source_compat import MA
from datetime import date
import numpy as np
SYMBOL = 'SHFE.rb2601'
KLINE_DURATION = 60 * 60
OBV_SHORT = 10
OBV_LONG = 30
PRICE_MA = 20
TRADE_VOLUME = 1
MAX_HOLD_BARS = 20

def calc_obv(close_series, volume_series):
    pass
    n = len(close_series)
    obv = np.zeros(n, dtype=float)
    obv[0] = volume_series.iloc[0] if hasattr(volume_series, 'iloc') else volume_series[0]
    for i in range(1, n):
        c_cur = close_series.iloc[i] if hasattr(close_series, 'iloc') else close_series[i]
        c_pre = close_series.iloc[i - 1] if hasattr(close_series, 'iloc') else close_series[i - 1]
        v_cur = volume_series.iloc[i] if hasattr(volume_series, 'iloc') else volume_series[i]
        if c_cur > c_pre:
            obv[i] = obv[i - 1] + v_cur
        elif c_cur < c_pre:
            obv[i] = obv[i - 1] - v_cur
        else:
            obv[i] = obv[i - 1]
    return obv

def moving_average(arr, period):
    pass
    result = np.full(len(arr), np.nan)
    for i in range(period - 1, len(arr)):
        result[i] = np.mean(arr[i - period + 1:i + 1])
    return result

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=500)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    pass
    last_signal = None
    hold_bars = 0
    last_bar_id = None
    while True:
        yield None
        if not api.is_changing(klines.iloc[-1], 'datetime'):
            continue
        current_bar_id = klines.iloc[-1]['id']
        if current_bar_id == last_bar_id:
            continue
        last_bar_id = current_bar_id
        n = len(klines)
        if n < OBV_LONG + 5:
            continue
        close = klines['close']
        volume = klines['volume']
        obv_arr = calc_obv(close, volume)
        obv_short_arr = moving_average(obv_arr, OBV_SHORT)
        obv_long_arr = moving_average(obv_arr, OBV_LONG)
        price_ma_arr = moving_average(close.values, PRICE_MA)
        obv_s_cur = obv_short_arr[-1]
        obv_s_pre = obv_short_arr[-2]
        obv_l_cur = obv_long_arr[-1]
        obv_l_pre = obv_long_arr[-2]
        cur_price = close.iloc[-1]
        price_ma_val = price_ma_arr[-1]
        if any((np.isnan(x) for x in [obv_s_cur, obv_s_pre, obv_l_cur, obv_l_pre, price_ma_val])):
            continue
        bull_signal = obv_s_pre <= obv_l_pre and obv_s_cur > obv_l_cur and (cur_price > price_ma_val)
        bear_signal = obv_s_pre >= obv_l_pre and obv_s_cur < obv_l_cur and (cur_price < price_ma_val)
        net_pos = position.pos_long - position.pos_short
        if net_pos != 0:
            hold_bars += 1
            if hold_bars >= MAX_HOLD_BARS:
                pass
                if net_pos > 0:
                    api.insert_order(SYMBOL, direction='SELL', offset='CLOSE', volume=position.pos_long)
                else:
                    api.insert_order(SYMBOL, direction='BUY', offset='CLOSE', volume=position.pos_short)
                last_signal = None
                hold_bars = 0
                continue
        else:
            hold_bars = 0
        if bull_signal and last_signal != 'long':
            if net_pos < 0:
                pass
                api.insert_order(SYMBOL, direction='BUY', offset='CLOSE', volume=position.pos_short)
            if net_pos <= 0:
                pass
                api.insert_order(SYMBOL, direction='BUY', offset='OPEN', volume=TRADE_VOLUME)
                last_signal = 'long'
                hold_bars = 0
        elif bear_signal and last_signal != 'short':
            if net_pos > 0:
                pass
                api.insert_order(SYMBOL, direction='SELL', offset='CLOSE', volume=position.pos_long)
            if net_pos >= 0:
                pass
                api.insert_order(SYMBOL, direction='SELL', offset='OPEN', volume=TRADE_VOLUME)
                last_signal = 'short'
                hold_bars = 0
        pass
