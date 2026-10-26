# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 60 * 60
TREND_PERIOD = 60
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
STOP_LOSS = 0.015
TAKE_PROFIT = 0.03

def calc_ma(closes, period):
    pass
    if len(closes) < period:
        return None
    return np.mean(closes[-period:])

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
            if len(klines) < TREND_PERIOD + RSI_PERIOD + 10:
                continue
            closes = klines['close'].values
            trend_ma = calc_ma(closes, TREND_PERIOD)
            if trend_ma is None:
                continue
            rsi = calc_rsi(closes, RSI_PERIOD)
            current_price = closes[-1]
            trend_up = current_price > trend_ma
            trend_down = current_price < trend_ma
            pass
            if position == 0 and trend_up and (rsi < RSI_OVERSOLD):
                position = 1
                entry_price = current_price
                pass
            elif position == 0 and trend_down and (rsi > RSI_OVERBOUGHT):
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
