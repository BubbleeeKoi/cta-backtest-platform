# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqBacktest, TqSim
from datetime import date
import numpy as np
SYMBOL = 'DCE.i2601'
KLINE_DURATION = 4 * 60 * 60
DMI_PERIOD = 14
ADX_PERIOD = 14
ADX_ENTRY = 25.0
ADX_EXIT = 20.0
BREAKOUT_PERIOD = 10
ATR_PERIOD = 14
ATR_MULTI = 2.0
TRADE_VOLUME = 1

def calc_dmi_adx(high, low, close, dmi_period=14, adx_period=14):
    pass
    n = len(close)
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    tr_arr = np.zeros(n)
    for i in range(1, n):
        h_cur, h_pre = (high[i], high[i - 1])
        l_cur, l_pre = (low[i], low[i - 1])
        c_pre = close[i - 1]
        tr_arr[i] = max(h_cur - l_cur, abs(h_cur - c_pre), abs(l_cur - c_pre))
        up_move = h_cur - h_pre
        down_move = l_pre - l_cur
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move
    tr14 = np.zeros(n)
    pdm14 = np.zeros(n)
    mdm14 = np.zeros(n)
    if n <= dmi_period:
        return (np.zeros(n), np.zeros(n), np.zeros(n))
    tr14[dmi_period] = np.sum(tr_arr[1:dmi_period + 1])
    pdm14[dmi_period] = np.sum(plus_dm[1:dmi_period + 1])
    mdm14[dmi_period] = np.sum(minus_dm[1:dmi_period + 1])
    for i in range(dmi_period + 1, n):
        tr14[i] = tr14[i - 1] - tr14[i - 1] / dmi_period + tr_arr[i]
        pdm14[i] = pdm14[i - 1] - pdm14[i - 1] / dmi_period + plus_dm[i]
        mdm14[i] = mdm14[i - 1] - mdm14[i - 1] / dmi_period + minus_dm[i]
    plus_di = np.where(tr14 > 0, pdm14 / tr14 * 100, 0.0)
    minus_di = np.where(tr14 > 0, mdm14 / tr14 * 100, 0.0)
    di_sum = plus_di + minus_di
    dx = np.where(di_sum > 0, np.abs(plus_di - minus_di) / di_sum * 100, 0.0)
    adx = np.zeros(n)
    start_idx = dmi_period + adx_period
    if n <= start_idx:
        return (plus_di, minus_di, adx)
    adx[start_idx] = np.mean(dx[dmi_period:dmi_period + adx_period])
    for i in range(start_idx + 1, n):
        adx[i] = (adx[i - 1] * (adx_period - 1) + dx[i]) / adx_period
    return (plus_di, minus_di, adx)

def calc_atr(high, low, close, period=14):
    pass
    n = len(close)
    tr_arr = np.zeros(n)
    for i in range(1, n):
        tr_arr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
    atr = np.zeros(n)
    if n <= period:
        return atr
    atr[period] = np.mean(tr_arr[1:period + 1])
    for i in range(period + 1, n):
        atr[i] = (atr[i - 1] * (period - 1) + tr_arr[i]) / period
    return atr

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=600)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    pass
    last_signal = None
    stop_loss_price = None
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
        min_data = DMI_PERIOD + ADX_PERIOD + BREAKOUT_PERIOD + 5
        if n < min_data:
            continue
        high_arr = klines['high'].values.astype(float)
        low_arr = klines['low'].values.astype(float)
        close_arr = klines['close'].values.astype(float)
        plus_di, minus_di, adx = calc_dmi_adx(high_arr, low_arr, close_arr, DMI_PERIOD, ADX_PERIOD)
        atr_arr = calc_atr(high_arr, low_arr, close_arr, ATR_PERIOD)
        adx_cur = adx[-1]
        adx_pre = adx[-2]
        pdi_cur = plus_di[-1]
        mdi_cur = minus_di[-1]
        pdi_pre = plus_di[-2]
        mdi_pre = minus_di[-2]
        atr_cur = atr_arr[-1]
        close_cur = close_arr[-1]
        if adx_cur == 0 or atr_cur == 0:
            continue
        recent_high = np.max(high_arr[-BREAKOUT_PERIOD - 1:-1])
        recent_low = np.min(low_arr[-BREAKOUT_PERIOD - 1:-1])
        net_pos = position.pos_long - position.pos_short
        if net_pos > 0 and stop_loss_price is not None:
            new_stop = close_cur - atr_cur * ATR_MULTI
            stop_loss_price = max(stop_loss_price, new_stop)
        elif net_pos < 0 and stop_loss_price is not None:
            new_stop = close_cur + atr_cur * ATR_MULTI
            stop_loss_price = min(stop_loss_price, new_stop)
        if net_pos > 0:
            exit_reason = None
            if stop_loss_price is not None and close_cur < stop_loss_price:
                exit_reason = f'触及追踪止损 {stop_loss_price:.1f}'
            elif adx_cur < ADX_EXIT:
                exit_reason = f'ADX={adx_cur:.1f} 跌破出场阈值 {ADX_EXIT}'
            elif mdi_cur > pdi_cur and mdi_pre <= pdi_pre:
                exit_reason = f'方向反转：-DI({mdi_cur:.1f}) 上穿 +DI({pdi_cur:.1f})'
            if exit_reason:
                pass
                api.insert_order(SYMBOL, direction='SELL', offset='CLOSE', volume=position.pos_long)
                last_signal = None
                stop_loss_price = None
        elif net_pos < 0:
            exit_reason = None
            if stop_loss_price is not None and close_cur > stop_loss_price:
                exit_reason = f'触及追踪止损 {stop_loss_price:.1f}'
            elif adx_cur < ADX_EXIT:
                exit_reason = f'ADX={adx_cur:.1f} 跌破出场阈值 {ADX_EXIT}'
            elif pdi_cur > mdi_cur and pdi_pre <= mdi_pre:
                exit_reason = f'方向反转：+DI({pdi_cur:.1f}) 上穿 -DI({mdi_cur:.1f})'
            if exit_reason:
                pass
                api.insert_order(SYMBOL, direction='BUY', offset='CLOSE', volume=position.pos_short)
                last_signal = None
                stop_loss_price = None
        net_pos = position.pos_long - position.pos_short
        if net_pos == 0:
            bull_entry = adx_cur >= ADX_ENTRY and pdi_cur > mdi_cur and (close_cur > recent_high) and (last_signal != 'long')
            bear_entry = adx_cur >= ADX_ENTRY and mdi_cur > pdi_cur and (close_cur < recent_low) and (last_signal != 'short')
            if bull_entry:
                stop_loss_price = close_cur - atr_cur * ATR_MULTI
                pass
                api.insert_order(SYMBOL, direction='BUY', offset='OPEN', volume=TRADE_VOLUME)
                last_signal = 'long'
            elif bear_entry:
                stop_loss_price = close_cur + atr_cur * ATR_MULTI
                pass
                api.insert_order(SYMBOL, direction='SELL', offset='OPEN', volume=TRADE_VOLUME)
                last_signal = 'short'
        trend_state = '震荡' if adx_cur < 20 else '弱趋势' if adx_cur < 25 else '强趋势'
        direction = '+DI主导(多)' if pdi_cur > mdi_cur else '-DI主导(空)'
        pass
