# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqAccount
from .._source_compat import RSI, ATR
import pandas as pd
import numpy as np

class FibonacciStrategy:
    pass

    def __init__(self, api, symbol, fib_levels=[0.236, 0.382, 0.5, 0.618, 0.786], rsi_period=14, rsi_oversold=35, rsi_overbought=65, atr_multi=2.5):
        self.api = api
        self.symbol = symbol
        self.fib_levels = fib_levels
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.atr_multi = atr_multi
        self.position = 0
        self.entry_price = 0
        self.highest = 0
        self.lowest = 0
        self.fib_levels_dict = {}

    def calculate_fib_retracement(self, klines):
        pass
        if len(klines) < 20:
            return {}
        self.highest = klines['high'].iloc[-20:].max()
        self.lowest = klines['low'].iloc[-20:].min()
        range_val = self.highest - self.lowest
        levels = {}
        for level in self.fib_levels:
            levels[level] = self.highest - range_val * level
        self.fib_levels_dict = levels
        return levels

    def calculate_rsi(self, klines):
        pass
        if len(klines) < self.rsi_period + 1:
            return 50
        return RSI(klines, self.rsi_period).iloc[-1]

    def find_nearest_fib(self, price):
        pass
        if not self.fib_levels_dict:
            return None
        distances = {abs(price - v): k for k, v in self.fib_levels_dict.items()}
        nearest_level = distances[min(distances.keys())]
        return (nearest_level, self.fib_levels_dict[nearest_level])

    def on_bar(self, klines):
        pass
        if len(klines) < 30:
            return
        fib_levels = self.calculate_fib_retracement(klines)
        current_price = klines['close'].iloc[-1]
        rsi = self.calculate_rsi(klines)
        if self.position == 0:
            for level, price in fib_levels.items():
                if abs(current_price - price) / price < 0.005:
                    if rsi < self.rsi_oversold:
                        self.position = 1
                        self.entry_price = current_price
                        pass
                        break
        elif self.position == 1:
            atr = ATR(klines, 14).iloc[-1]
            if current_price < self.entry_price - atr * self.atr_multi:
                pass
                self.position = 0
                self.entry_price = 0
            elif rsi > self.rsi_overbought:
                pass
                self.position = 0
                self.entry_price = 0

def program(api):
    api = api
    symbol = 'SHFE.rb2505'
    strategy = FibonacciStrategy(api, symbol=symbol, fib_levels=[0.236, 0.382, 0.5, 0.618, 0.786], rsi_period=14, rsi_oversold=35, rsi_overbought=65, atr_multi=2.5)
    klines = api.get_kline_serial(symbol, 60)
    while True:
        yield None
        if api.is_changing(klines):
            strategy.on_bar(klines)
    api.close()
