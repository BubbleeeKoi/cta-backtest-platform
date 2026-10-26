# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import math
import datetime
import numpy as np
from .._source_compat import TqApi, TqAuth, TqSim, BacktestFinished
SYMBOL = 'KQ.m@SHFE.rb'
KLINE_FREQ = 60
Z_ENTRY = 2.0
Z_EXIT = 0.3
Z_STOP = 3.5
LOT_SIZE = 1
CLOSE_HOUR = 14
CLOSE_MINUTE = 50

class VwapCalculator:
    pass

    def __init__(self):
        self._reset()

    def _reset(self):
        pass
        self._cum_vol = 0.0
        self._cum_tp_vol = 0.0
        self._cum_tp2_vol = 0.0
        self.vwap = None
        self.std = None
        self.cum_vol = 0.0

    def update(self, high: float, low: float, close: float, volume: float, new_day: bool):
        pass
        if new_day:
            self._reset()
        if volume <= 0:
            return
        tp = (high + low + close) / 3.0
        self._cum_vol += volume
        self._cum_tp_vol += tp * volume
        self._cum_tp2_vol += tp * tp * volume
        self.vwap = self._cum_tp_vol / self._cum_vol
        self.cum_vol = self._cum_vol
        variance = self._cum_tp2_vol / self._cum_vol - self.vwap ** 2
        variance = max(variance, 0.0)
        self.std = math.sqrt(variance) if variance > 1e-10 else None

    def z_score(self, price: float) -> float | None:
        pass
        if self.vwap is None or self.std is None or self.std < 1e-10:
            return None
        return (price - self.vwap) / self.std

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_FREQ, data_length=500)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    vwap_calc = VwapCalculator()
    last_bar_date = None
    position_side = 0
    try:
        while True:
            yield None
            if not api.is_changing(klines.iloc[-1], 'datetime'):
                continue
            bar = klines.iloc[-2]
            bar_dt = source_datetime(bar['datetime'] / 1000000000.0, tz=datetime.timezone(datetime.timedelta(hours=8)))
            bar_date = bar_dt.date()
            bar_time = bar_dt.time()
            is_new_day = last_bar_date is not None and bar_date != last_bar_date
            last_bar_date = bar_date
            vwap_calc.update(high=bar['high'], low=bar['low'], close=bar['close'], volume=bar['volume'], new_day=is_new_day)
            if vwap_calc.cum_vol < 10 or vwap_calc.std is None:
                continue
            current_price = quote.last_price
            z = vwap_calc.z_score(current_price)
            if z is None:
                continue
            vwap = vwap_calc.vwap
            std = vwap_calc.std
            long_pos = position.pos_long_today + position.pos_long
            short_pos = position.pos_short_today + position.pos_short
            if bar_time.hour > CLOSE_HOUR or (bar_time.hour == CLOSE_HOUR and bar_time.minute >= CLOSE_MINUTE):
                if long_pos > 0:
                    api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                    pass
                    position_side = 0
                if short_pos > 0:
                    api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                    pass
                    position_side = 0
                continue
            if position_side == 1 and z < -Z_STOP:
                if long_pos > 0:
                    api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                    pass
                    position_side = 0
            elif position_side == -1 and z > Z_STOP:
                if short_pos > 0:
                    api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                    pass
                    position_side = 0
            elif position_side == 1 and abs(z) <= Z_EXIT:
                if long_pos > 0:
                    api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                    pass
                    position_side = 0
            elif position_side == -1 and abs(z) <= Z_EXIT:
                if short_pos > 0:
                    api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                    pass
                    position_side = 0
            elif position_side == 0:
                if z >= Z_ENTRY:
                    api.insert_order(SYMBOL, 'SELL', 'OPEN', LOT_SIZE, quote.bid_price1)
                    pass
                    position_side = -1
                elif z <= -Z_ENTRY:
                    api.insert_order(SYMBOL, 'BUY', 'OPEN', LOT_SIZE, quote.ask_price1)
                    pass
                    position_side = 1
    except BacktestFinished:
        bal = account.balance
        mdd = account.max_drawdown
        pass
        pass
        pass
        pass
        pass
    finally:
        api.close()
