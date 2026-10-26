# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth
import numpy as np
SYMBOL = 'SHFE.rb2505'
KLINE_DURATION = 60 * 60
FAST_MA = 10
SLOW_MA = 60
VOLUME_CONFIRM = 1.5
STOP_LOSS = 0.02
TAKE_PROFIT = 0.06

def program(api):
    api = api
    pass
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=150)
    position = 0
    entry_price = 0
    prev_fast_ma = None
    prev_slow_ma = None
    while True:
        yield None
        if api.is_changing(klines):
            if len(klines) < SLOW_MA + 20:
                continue
            closes = klines['close'].values
            volumes = klines['volume'].values
            fast_ma = np.mean(closes[-FAST_MA:])
            slow_ma = np.mean(closes[-SLOW_MA:])
            avg_volume = np.mean(volumes[-20:])
            current_volume = volumes[-1]
            current_price = closes[-1]
            if prev_fast_ma is None or prev_slow_ma is None:
                prev_fast_ma = fast_ma
                prev_slow_ma = slow_ma
                continue
            gold_cross = prev_fast_ma <= prev_slow_ma and fast_ma > slow_ma
            death_cross = prev_fast_ma >= prev_slow_ma and fast_ma < slow_ma
            volume_confirmed = current_volume > avg_volume * VOLUME_CONFIRM
            pass
            if position == 0 and gold_cross and volume_confirmed:
                position = 1
                entry_price = current_price
                pass
            elif position == 0 and death_cross and volume_confirmed:
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
            prev_fast_ma = fast_ma
            prev_slow_ma = slow_ma
