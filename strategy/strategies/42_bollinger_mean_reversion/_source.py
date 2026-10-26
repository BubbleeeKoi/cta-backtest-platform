# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 30 * 60
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
STOP_LOSS = 0.015
TAKE_PROFIT = 0.03

def calc_bollinger_bands(closes, period=20, std_dev=2.0):
    pass
    if len(closes) < period:
        return (None, None, None)
    recent = closes[-period:]
    ma = np.mean(recent)
    std = np.std(recent)
    upper = ma + std_dev * std
    lower = ma - std_dev * std
    return (upper, ma, lower)

def calc_rsi(closes, period=14):
    pass
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes[-period - 1:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains)
    avg_loss = np.mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    return rsi

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    position = 0
    entry_price = 0
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < BB_PERIOD + RSI_PERIOD + 10:
                continue
            closes = klines['close'].values
            upper, middle, lower = calc_bollinger_bands(closes, BB_PERIOD, BB_STD)
            if upper is None:
                continue
            rsi = calc_rsi(closes, RSI_PERIOD)
            current_price = closes[-1]
            pass
            if position == 0 and current_price <= lower and (rsi < 35):
                position = 1
                entry_price = current_price
                pass
            elif position == 0 and current_price >= upper and (rsi > 65):
                position = -1
                entry_price = current_price
                pass
            elif position != 0:
                pnl = (current_price - entry_price) / entry_price if position == 1 else (entry_price - current_price) / entry_price
                if pnl <= -STOP_LOSS:
                    pass
                    position = 0
                elif pnl >= TAKE_PROFIT:
                    pass
                    position = 0
