# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim
from .._source_compat import BOLL
import pandas as pd
SYMBOL = 'SHFE.rb2405'
KLINE_FREQ = 900
BOLL_PERIOD = 20
BOLL_STD = 2.0
LOT_SIZE = 1
CLOSE_HOUR = 14
CLOSE_MINUTE = 50

def program(api):
    api = api
    pass
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_FREQ, data_length=BOLL_PERIOD + 10)
    position = 0
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        if len(klines) < BOLL_PERIOD + 5:
            continue
        df = pd.DataFrame(klines)
        df['close'] = df['close'].astype(float)
        boll = BOLL(df['close'], period=BOLL_PERIOD, std_multiplier=BOLL_STD)
        df['boll_mid'] = boll['mid'].values
        df['boll_upp'] = boll['upp'].values
        df['boll_low'] = boll['low'].values
        current_price = df['close'].iloc[-1]
        boll_mid = df['boll_mid'].iloc[-1]
        boll_upp = df['boll_upp'].iloc[-1]
        boll_low = df['boll_low'].iloc[-1]
        current_time = pd.to_datetime(df['datetime'].iloc[-1], unit='ns')
        hour = current_time.hour
        minute = current_time.minute
        if hour > CLOSE_HOUR or (hour == CLOSE_HOUR and minute >= CLOSE_MINUTE):
            if position != 0:
                pass
                if position > 0:
                    api.insert_order(symbol=SYMBOL, direction='SELL', offset='CLOSE', volume=LOT_SIZE)
                else:
                    api.insert_order(symbol=SYMBOL, direction='BUY', offset='CLOSE', volume=LOT_SIZE)
                position = 0
            continue
        if position == 0:
            if current_price <= boll_low:
                pass
                api.insert_order(symbol=SYMBOL, direction='BUY', offset='OPEN', volume=LOT_SIZE)
                position = 1
            elif current_price >= boll_upp:
                pass
                api.insert_order(symbol=SYMBOL, direction='SELL', offset='OPEN', volume=LOT_SIZE)
                position = -1
        elif position == 1 and current_price >= boll_mid:
            pass
            api.insert_order(symbol=SYMBOL, direction='SELL', offset='CLOSE', volume=LOT_SIZE)
            position = 0
        elif position == -1 and current_price <= boll_mid:
            pass
            api.insert_order(symbol=SYMBOL, direction='BUY', offset='CLOSE', volume=LOT_SIZE)
            position = 0
    api.close()
