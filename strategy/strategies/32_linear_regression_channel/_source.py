# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
from .._source_compat import TqApi, TqAuth, TqSim, BacktestFinished
from .._source_compat import sma
SYMBOL = 'KQ.m@SHFE.rb'
KLINE_PERIOD = 3600
LR_PERIOD = 30
CHANNEL_K = 2.0
EXIT_K = 0.3
STOP_K = 1.0
LOT_SIZE = 1
SLOPE_FILTER = True

def linear_regression_channel(closes: np.ndarray):
    pass
    n = len(closes)
    x = np.arange(n, dtype=float)
    y = closes
    x_mean = x.mean()
    y_mean = y.mean()
    ss_xx = np.sum((x - x_mean) ** 2)
    ss_xy = np.sum((x - x_mean) * (y - y_mean))
    if ss_xx < 1e-10:
        return (None, None, None, None, None)
    slope = ss_xy / ss_xx
    intercept = y_mean - slope * x_mean
    y_pred = intercept + slope * x
    residuals = y - y_pred
    if n > 2:
        se = np.sqrt(np.sum(residuals ** 2) / (n - 2))
    else:
        se = 0.0
    mid = intercept + slope * (n - 1)
    upper = mid + CHANNEL_K * se
    lower = mid - CHANNEL_K * se
    return (mid, upper, lower, slope, se)

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_PERIOD, data_length=200)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    pass
    position_side = 0
    prev_above_upper = False
    prev_below_lower = False
    try:
        while True:
            yield None
            if not api.is_changing(klines.iloc[-1], 'datetime'):
                continue
            close_series = klines['close'].dropna().values
            if len(close_series) < LR_PERIOD + 5:
                continue
            closes = close_series[-(LR_PERIOD + 1):-1]
            mid, upper, lower, slope, se = linear_regression_channel(closes)
            if mid is None or se < 1e-06:
                continue
            current_price = quote.last_price
            if current_price != current_price:
                continue
            long_pos = position.pos_long_today + position.pos_long
            short_pos = position.pos_short_today + position.pos_short
            above_upper = current_price > upper
            below_lower = current_price < lower
            near_mid = abs(current_price - mid) <= EXIT_K * se
            if position_side == 1:
                stop_price = mid - STOP_K * se
                if current_price < stop_price and long_pos > 0:
                    api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                    pass
                    position_side = 0
                    prev_above_upper = False
            elif position_side == -1:
                stop_price = mid + STOP_K * se
                if current_price > stop_price and short_pos > 0:
                    api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                    pass
                    position_side = 0
                    prev_below_lower = False
            if position_side == 1 and near_mid and (long_pos > 0):
                api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                pass
                position_side = 0
                prev_above_upper = False
            elif position_side == -1 and near_mid and (short_pos > 0):
                api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                pass
                position_side = 0
                prev_below_lower = False
            if position_side == 0:
                if above_upper and (not prev_above_upper):
                    if not SLOPE_FILTER or slope > 0:
                        api.insert_order(SYMBOL, 'BUY', 'OPEN', LOT_SIZE, quote.ask_price1)
                        pass
                        position_side = 1
                elif below_lower and (not prev_below_lower):
                    if not SLOPE_FILTER or slope < 0:
                        api.insert_order(SYMBOL, 'SELL', 'OPEN', LOT_SIZE, quote.bid_price1)
                        pass
                        position_side = -1
            prev_above_upper = above_upper
            prev_below_lower = below_lower
            pass
    except BacktestFinished:
        bal = account.balance
        pass
        pass
        pass
    finally:
        api.close()
