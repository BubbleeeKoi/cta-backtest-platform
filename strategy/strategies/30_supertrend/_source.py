# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import numpy as np
from .._source_compat import TqApi, TqAuth, TqSim, BacktestFinished
from .._source_compat import atr
SYMBOL = 'KQ.m@SHFE.rb'
KLINE_FREQ = 60 * 15
ATR_PERIOD = 10
MULTIPLIER = 3.0
LOT_SIZE = 1

def compute_supertrend(df, period: int, multiplier: float):
    pass
    high = df['high']
    low = df['low']
    close = df['close']
    atr_series = atr(df, period)
    hl2 = (high + low) / 2.0
    bub = hl2 + multiplier * atr_series
    blb = hl2 - multiplier * atr_series
    n = len(df)
    fub = np.full(n, np.nan)
    flb = np.full(n, np.nan)
    st_value = np.full(n, np.nan)
    st_dir = np.zeros(n, dtype=int)
    fub[0] = bub.iloc[0]
    flb[0] = blb.iloc[0]
    st_value[0] = fub[0]
    st_dir[0] = -1
    for i in range(1, n):
        if bub.iloc[i] < fub[i - 1] or close.iloc[i - 1] > fub[i - 1]:
            fub[i] = bub.iloc[i]
        else:
            fub[i] = fub[i - 1]
        if blb.iloc[i] > flb[i - 1] or close.iloc[i - 1] < flb[i - 1]:
            flb[i] = blb.iloc[i]
        else:
            flb[i] = flb[i - 1]
        if st_dir[i - 1] == -1:
            if close.iloc[i] > fub[i]:
                st_value[i] = flb[i]
                st_dir[i] = 1
            else:
                st_value[i] = fub[i]
                st_dir[i] = -1
        elif close.iloc[i] < flb[i]:
            st_value[i] = fub[i]
            st_dir[i] = -1
        else:
            st_value[i] = flb[i]
            st_dir[i] = 1
    df = df.copy()
    df['st_value'] = st_value
    df['st_dir'] = st_dir
    return df

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_FREQ, data_length=ATR_PERIOD + 50)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    prev_dir = 0
    try:
        while True:
            yield None
            if not api.is_changing(klines.iloc[-1], 'datetime'):
                continue
            if len(klines) < ATR_PERIOD + 5:
                continue
            recent = klines.copy()
            recent = compute_supertrend(recent, ATR_PERIOD, MULTIPLIER)
            cur_dir = int(recent['st_dir'].iloc[-2])
            cur_st = float(recent['st_value'].iloc[-2])
            long_pos = position.pos_long_today + position.pos_long
            short_pos = position.pos_short_today + position.pos_short
            if prev_dir != 0 and cur_dir != prev_dir:
                if cur_dir == 1:
                    if short_pos > 0:
                        api.insert_order(symbol=SYMBOL, direction='BUY', offset='CLOSE', volume=short_pos, limit_price=quote.ask_price1)
                        pass
                    api.insert_order(symbol=SYMBOL, direction='BUY', offset='OPEN', volume=LOT_SIZE, limit_price=quote.ask_price1)
                    pass
                elif cur_dir == -1:
                    if long_pos > 0:
                        api.insert_order(symbol=SYMBOL, direction='SELL', offset='CLOSE', volume=long_pos, limit_price=quote.bid_price1)
                        pass
                    api.insert_order(symbol=SYMBOL, direction='SELL', offset='OPEN', volume=LOT_SIZE, limit_price=quote.bid_price1)
                    pass
            prev_dir = cur_dir
    except BacktestFinished:
        stat = account
        pass
        pass
        pass
        pass
        pass
    finally:
        api.close()
