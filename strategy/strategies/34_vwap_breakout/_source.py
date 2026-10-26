# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqAccount
from .._source_compat import ATR, MA
import pandas as pd
import numpy as np

class VWAPStrategy:
    pass

    def __init__(self, api, symbol, n1=5, n2=20, volume_factor=1.5, atr_multi=2.0, fixed_profit=50):
        self.api = api
        self.symbol = symbol
        self.n1 = n1
        self.n2 = n2
        self.volume_factor = volume_factor
        self.atr_multi = atr_multi
        self.fixed_profit = fixed_profit
        self.position = 0
        self.entry_price = 0
        self.vwap = 0

    def calculate_vwap(self, klines):
        pass
        if len(klines) < self.n2:
            return 0
        df = klines.iloc[-self.n2:].copy()
        df['pv'] = df['close'] * df['volume']
        vwap = df['pv'].sum() / df['volume'].sum()
        return vwap

    def calculate_atr(self, klines):
        pass
        if len(klines) < 14:
            return 0
        return ATR(klines, 14).iloc[-1]

    def check_volume_surge(self, klines):
        pass
        if len(klines) < self.n1 + 1:
            return False
        recent_vol = klines['volume'].iloc[-self.n1:].mean()
        prev_vol = klines['volume'].iloc[-self.n1 - 5:-self.n1].mean()
        return recent_vol > prev_vol * self.volume_factor

    def on_bar(self, klines):
        pass
        if len(klines) < self.n2 + 1:
            return
        current_price = klines['close'].iloc[-1]
        self.vwap = self.calculate_vwap(klines)
        atr = self.calculate_atr(klines)
        if self.position == 0:
            prev_price = klines['close'].iloc[-2]
            if prev_price < self.vwap and current_price > self.vwap and self.check_volume_surge(klines):
                self.position = 1
                self.entry_price = current_price
                pass
            elif prev_price > self.vwap and current_price < self.vwap and self.check_volume_surge(klines):
                self.position = -1
                self.entry_price = current_price
                pass
        elif self.position == 1:
            if current_price < self.entry_price - atr * self.atr_multi:
                pass
                self.position = 0
                self.entry_price = 0
            elif current_price > self.entry_price + self.fixed_profit:
                pass
                self.position = 0
                self.entry_price = 0
            elif current_price < self.vwap:
                pass
                self.position = 0
                self.entry_price = 0
        elif self.position == -1:
            if current_price > self.entry_price + atr * self.atr_multi:
                pass
                self.position = 0
                self.entry_price = 0
            elif current_price < self.entry_price - self.fixed_profit:
                pass
                self.position = 0
                self.entry_price = 0
            elif current_price > self.vwap:
                pass
                self.position = 0
                self.entry_price = 0

def program(api):
    api = api
    symbol = 'SHFE.rb2505'
    strategy = VWAPStrategy(api, symbol=symbol, n1=5, n2=20, volume_factor=1.5, atr_multi=2.0, fixed_profit=50)
    klines = api.get_kline_serial(symbol, 60)
    while True:
        yield None
        if api.is_changing(klines):
            strategy.on_bar(klines)
    api.close()
