# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
import numpy as np
import pandas as pd
import time
SYMBOL = 'SHFE.rb2501'
KLINE_DUR = 1800
BOLL_PERIOD = 20
BOLL_MULT = 2.0
ATR_PERIOD = 14
ADX_PERIOD = 14
VOL_CONE_WINDOWS = [5, 20, 60]
UPPER_PCT = 75
LOWER_PCT = 25
TARGET_VOL = 0.15
BASE_LOT = 1
VOL_ALERT_PCT = 90

def calc_atr(high, low, close, period=14):
    pass
    if len(high) < period + 1:
        return np.nan
    tr_list = []
    for i in range(-period, 0):
        tr1 = high.iloc[i] - low.iloc[i]
        tr2 = abs(high.iloc[i] - close.iloc[i - 1])
        tr3 = abs(low.iloc[i] - close.iloc[i - 1])
        tr_list.append(max(tr1, tr2, tr3))
    return np.mean(tr_list)

def calc_adx_approx(high, low, close, period=14):
    pass
    if len(close) < period * 2 + 1:
        return np.nan
    returns = close.pct_change().dropna()
    if len(returns) < period:
        return np.nan
    up = returns.clip(lower=0).std()
    down = (-returns.clip(upper=0)).std()
    total = returns.std()
    if total == 0:
        return 0
    plus_dm = up
    minus_dm = down
    tr_val = total
    plus_di = plus_dm / tr_val * 100 if tr_val > 0 else 0
    minus_di = minus_dm / tr_val * 100 if tr_val > 0 else 0
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0
    dx = abs(plus_di - minus_di) / di_sum * 100
    return min(dx, 100)

def calc_vol_percentile(close, current_vol, window_days, kline_dur):
    pass
    if len(close) < window_days * 86400 // kline_dur + 1:
        return 0.5
    klines_needed = window_days * 86400 // kline_dur
    vol_series = []
    for i in range(len(close) - klines_needed):
        segment = close.iloc[i:i + klines_needed]
        if len(segment) >= klines_needed // 2:
            vol = segment.pct_change().std() * np.sqrt(252)
            if not np.isnan(vol) and vol > 0:
                vol_series.append(vol)
    if len(vol_series) < 5:
        return 0.5
    current_annual_vol = current_vol * np.sqrt(252)
    sorted_vols = sorted(vol_series)
    n = len(sorted_vols)
    rank = sum((1 for v in sorted_vols if v <= current_annual_vol))
    percentile = rank / n
    return percentile

def volatility_cone_limits(close, kline_dur, windows):
    pass
    limits = {}
    for w in windows:
        klines_needed = w * 86400 // kline_dur
        if len(close) < klines_needed + 1:
            limits[w] = (np.nan, np.nan)
            continue
        vol_series = []
        for i in range(len(close) - klines_needed + 1):
            segment = close.iloc[i:i + klines_needed]
            if len(segment) >= klines_needed // 2:
                vol = segment.pct_change().std() * np.sqrt(252)
                if not np.isnan(vol) and vol > 0:
                    vol_series.append(vol)
        if len(vol_series) < 5:
            limits[w] = (np.nan, np.nan)
            continue
        vol_arr = np.array(vol_series)
        upper = np.percentile(vol_arr, UPPER_PCT)
        lower = np.percentile(vol_arr, LOWER_PCT)
        limits[w] = (upper, lower)
    return limits

def calc_adaptive_stop_loss(entry_price, current_atr, vol_percentile, direction, trailing=False, peak_price=None):
    pass
    if np.isnan(vol_percentile):
        vol_percentile = 0.5
    if vol_percentile > 0.75:
        atr_mult = 3.0
    elif vol_percentile > 0.25:
        atr_mult = 2.0
    else:
        atr_mult = 1.5
    if trailing and peak_price is not None:
        if direction == 1:
            stop = peak_price - atr_mult * current_atr
        else:
            stop = peak_price + atr_mult * current_atr
    elif direction == 1:
        stop = entry_price - atr_mult * current_atr
    else:
        stop = entry_price + atr_mult * current_atr
    return stop

def program(api):
    api = api
    pass
    pass
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=max(VOL_CONE_WINDOWS) * 86400 // KLINE_DUR + BOLL_PERIOD * 2)
    pass
    pass
    pass
    target_task = TargetPosTask(api, SYMBOL)
    position = 0
    entry_price = None
    entry_vol_pct = None
    peak_price = None
    in_position = False
    last_vol_alert = False
    with api.register_update_notify():
        while True:
            yield None
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            if len(klines) < max(VOL_CONE_WINDOWS) * 86400 // KLINE_DUR + BOLL_PERIOD * 2:
                continue
            close = klines['close']
            high = klines['high']
            low = klines['low']
            atr = calc_atr(high, low, close, ATR_PERIOD)
            if np.isnan(atr):
                continue
            adx = calc_adx_approx(high, low, close, ADX_PERIOD)
            if np.isnan(adx):
                continue
            boll_period = BOLL_PERIOD
            if len(close) < boll_period:
                continue
            ma = close.iloc[-boll_period:].mean()
            std = close.iloc[-boll_period:].std()
            upper_band = ma + BOLL_MULT * std
            lower_band = ma - BOLL_MULT * std
            current_price = close.iloc[-1]
            current_vol = atr / current_price if current_price > 0 else 0
            cone_limits = volatility_cone_limits(close, KLINE_DUR, VOL_CONE_WINDOWS)
            vol_pct = calc_vol_percentile(close, current_vol, VOL_CONE_WINDOWS[-1], KLINE_DUR)
            weights = [0.2, 0.3, 0.5]
            vol_pct_weighted = 0.5
            valid_cones = 0
            for i, w in enumerate(VOL_CONE_WINDOWS):
                if w in cone_limits and (not np.isnan(cone_limits[w][0])):
                    annual_vol = current_vol * np.sqrt(252)
                    upper, lower = cone_limits[w]
                    if upper > lower:
                        pct = (annual_vol - lower) / (upper - lower)
                        pct = max(0, min(1, pct))
                        vol_pct_weighted += weights[i] * pct
                        valid_cones += 1
            if valid_cones == 0:
                vol_pct_weighted = 0.5
            vol_percentile = vol_pct_weighted
            vol_alert = vol_percentile > VOL_ALERT_PCT / 100
            if vol_alert != last_vol_alert:
                if vol_alert:
                    pass
                else:
                    pass
                last_vol_alert = vol_alert
            if not in_position:
                if current_price > upper_band and adx > 25 and (not vol_alert):
                    direction = 1
                    entry_price = current_price
                    entry_vol_pct = vol_percentile
                    peak_price = current_price
                    current_annual_vol = current_vol * np.sqrt(252)
                    if current_annual_vol > 0:
                        vol_ratio = TARGET_VOL / current_annual_vol
                        target_lot = int(min(vol_ratio * BASE_LOT, 10))
                        target_lot = max(target_lot, 1)
                    else:
                        target_lot = BASE_LOT
                    stop_loss = calc_adaptive_stop_loss(entry_price, atr, vol_percentile, direction)
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    position = target_lot
                    target_task.set_target_volume(position)
                    in_position = True
                elif current_price < lower_band and adx > 25 and (vol_percentile > 0.5):
                    direction = -1
                    entry_price = current_price
                    entry_vol_pct = vol_percentile
                    peak_price = current_price
                    current_annual_vol = current_vol * np.sqrt(252)
                    if current_annual_vol > 0:
                        vol_ratio = TARGET_VOL / current_annual_vol
                        target_lot = -max(1, int(min(vol_ratio * BASE_LOT, 10)))
                    else:
                        target_lot = -BASE_LOT
                    stop_loss = calc_adaptive_stop_loss(entry_price, atr, vol_percentile, direction)
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    position = target_lot
                    target_task.set_target_volume(position)
                    in_position = True
            else:
                direction = 1 if position > 0 else -1
                if direction == 1:
                    if peak_price is None or current_price > peak_price:
                        peak_price = current_price
                elif peak_price is None or current_price < peak_price:
                    peak_price = current_price
                stop_loss = calc_adaptive_stop_loss(entry_price, atr, vol_percentile, direction, trailing=True, peak_price=peak_price)
                stop_triggered = False
                if direction == 1 and current_price < stop_loss:
                    stop_triggered = True
                elif direction == -1 and current_price > stop_loss:
                    stop_triggered = True
                if vol_percentile > 0.9 and abs(position) > 1:
                    new_pos = int(abs(position) * 0.5) * (1 if direction == 1 else -1)
                    pass
                    position = new_pos
                    target_task.set_target_volume(position)
                if stop_triggered:
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    pass
                    position = 0
                    target_task.set_target_volume(0)
                    in_position = False
                    entry_price = None
                    peak_price = None
                elif direction == 1 and peak_price > entry_price * 1.02 or (direction == -1 and peak_price < entry_price * 0.98):
                    breakeven = entry_price * (1.01 if direction == 1 else 0.99)
                    if direction == 1 and current_price < breakeven or (direction == -1 and current_price > breakeven):
                        pass
                        position = 0
                        target_task.set_target_volume(0)
                        in_position = False
                        entry_price = None
                        peak_price = None
