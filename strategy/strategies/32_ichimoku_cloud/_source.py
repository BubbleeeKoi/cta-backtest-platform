# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import datetime
from .._source_compat import TqApi, TqAuth, TqSim, BacktestFinished
SYMBOL = 'KQ.m@SHFE.rb'
KLINE_PERIOD = 86400
TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_PERIOD = 52
CHIKOU_OFFSET = 26
LOT_SIZE = 1

class IchimokuCloud:
    pass

    def __init__(self, tenkan_period: int=9, kijun_period: int=26, senkou_period: int=52, chikou_offset: int=26):
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_period = senkou_period
        self.chikou_offset = chikou_offset
        self.tenkan_sen = None
        self.kijun_sen = None
        self.senkou_a = None
        self.senkou_b = None
        self.chikou_span = None
        self.cloud_shift_a = None
        self.cloud_shift_b = None

    def _calculate_midprice(self, klines, period: int) -> float | None:
        pass
        if len(klines) < period:
            return None
        high = klines['high'].tail(period).max()
        low = klines['low'].tail(period).min()
        return (high + low) / 2.0

    def update(self, klines) -> bool:
        pass
        n = len(klines)
        min_required = max(self.tenkan_period, self.kijun_period, self.senkou_period) + self.chikou_offset
        if n < min_required:
            return False
        tenkan_mid = self._calculate_midprice(klines, self.tenkan_period)
        if tenkan_mid is None:
            return False
        self.tenkan_sen = tenkan_mid
        kijun_mid = self._calculate_midprice(klines, self.kijun_period)
        if kijun_mid is None:
            return False
        self.kijun_sen = kijun_mid
        senkou_a_mid = (self.tenkan_sen + self.kijun_sen) / 2.0
        if n >= self.chikou_offset + 1:
            self.senkou_a = senkou_a_mid
            idx = n - self.chikou_offset - 1
            if idx >= 0:
                past_klines = klines.iloc[:idx + 1]
                if len(past_klines) >= 2:
                    past_tenkan = self._calculate_midprice(past_klines, self.tenkan_period)
                    past_kijun = self._calculate_midprice(past_klines, self.kijun_period)
                    if past_tenkan and past_kijun:
                        self.cloud_shift_a = (past_tenkan + past_kijun) / 2.0
        senkou_b_mid = self._calculate_midprice(klines, self.senkou_period)
        if senkou_b_mid is None:
            return False
        self.senkou_b = senkou_b_mid
        idx = n - self.chikou_offset - 1
        if idx >= 0:
            past_klines = klines.iloc[:idx + 1]
            if len(past_klines) >= self.senkou_period:
                self.cloud_shift_b = past_klines['high'].tail(self.senkou_period).max() + past_klines['low'].tail(self.senkou_period).min()
                self.cloud_shift_b /= 2.0
        if n > self.chikou_offset:
            self.chikou_span = klines.iloc[-(self.chikou_offset + 1)]['close']
        return True

    def get_signal(self, current_price: float, past_price_26: float=None) -> dict:
        pass
        if None in (self.tenkan_sen, self.kijun_sen, self.senkou_a, self.senkou_b, self.chikou_span):
            return {'signal': 'none', 'reason': '指标未就绪'}
        cloud_top = max(self.senkou_a, self.senkou_b)
        cloud_bottom = min(self.senkou_a, self.senkou_b)
        cloud_green = self.senkou_a > self.senkou_b
        chikou_above = past_price_26 is not None and self.chikou_span > past_price_26
        chikou_below = past_price_26 is not None and self.chikou_span < past_price_26
        tenkan_cross_up = False
        if current_price > cloud_top:
            if self.tenkan_sen > self.kijun_sen:
                if chikou_above:
                    return {'signal': 'buy', 'reason': '转换线>基准线 + 价格>云层 + 延迟线确认'}
        if current_price < cloud_bottom:
            if self.tenkan_sen < self.kijun_sen:
                if chikou_below:
                    return {'signal': 'sell', 'reason': '转换线<基准线 + 价格<云层 + 延迟线确认'}
        if current_price > cloud_top and self.tenkan_sen > self.kijun_sen:
            return {'signal': 'keep_long', 'reason': '多头趋势延续'}
        if current_price < cloud_bottom and self.tenkan_sen < self.kijun_sen:
            return {'signal': 'keep_short', 'reason': '空头趋势延续'}
        return {'signal': 'none', 'reason': '无明确信号'}

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_PERIOD, data_length=200)
    quote = api.get_quote(SYMBOL)
    account = api.get_account()
    position = api.get_position(SYMBOL)
    pass
    ichimoku = IchimokuCloud(tenkan_period=TENKAN_PERIOD, kijun_period=KIJUN_PERIOD, senkou_period=SENKOU_PERIOD, chikou_offset=CHIKOU_OFFSET)
    position_side = 0
    last_tenkan = None
    last_kijun = None
    try:
        while True:
            yield None
            if not api.is_changing(klines.iloc[-1], 'datetime'):
                continue
            bar = klines.iloc[-2]
            if not ichimoku.update(klines):
                continue
            current_price = quote.last_price
            long_pos = position.pos_long_today + position.pos_long
            short_pos = position.pos_short_today + position.pos_short
            past_price_26 = None
            if len(klines) > CHIKOU_OFFSET + 1:
                past_price_26 = klines.iloc[-(CHIKOU_OFFSET + 1)]['close']
            tenkan = ichimoku.tenkan_sen
            kijun = ichimoku.kijun_sen
            cross_up = last_tenkan is not None and last_kijun is not None and (last_tenkan <= last_kijun) and (tenkan > kijun)
            cross_down = last_tenkan is not None and last_kijun is not None and (last_tenkan >= last_kijun) and (tenkan < kijun)
            last_tenkan = tenkan
            last_kijun = kijun
            signal_info = ichimoku.get_signal(current_price, past_price_26)
            if position_side == 1:
                if signal_info['signal'] in ['sell', 'none']:
                    if cross_down or (current_price < ichimoku.kijun_sen and ichimoku.kijun_sen is not None):
                        if long_pos > 0:
                            api.insert_order(SYMBOL, 'SELL', 'CLOSE', long_pos, quote.bid_price1)
                            pass
                            position_side = 0
            elif position_side == -1:
                if signal_info['signal'] in ['buy', 'none']:
                    if cross_up or (current_price > ichimoku.kijun_sen and ichimoku.kijun_sen is not None):
                        if short_pos > 0:
                            api.insert_order(SYMBOL, 'BUY', 'CLOSE', short_pos, quote.ask_price1)
                            pass
                            position_side = 0
            elif position_side == 0:
                if cross_up:
                    cloud_top = max(ichimoku.senkou_a, ichimoku.senkou_b) if ichimoku.senkou_a and ichimoku.senkou_b else None
                    if cloud_top is None or current_price > cloud_top:
                        past_for_chikou = past_price_26 if past_price_26 else klines.iloc[-30]['close'] if len(klines) > 30 else None
                        if past_for_chikou and ichimoku.chikou_span and (ichimoku.chikou_span > past_for_chikou):
                            api.insert_order(SYMBOL, 'BUY', 'OPEN', LOT_SIZE, quote.ask_price1)
                            pass
                            position_side = 1
                elif cross_down:
                    cloud_bottom = min(ichimoku.senkou_a, ichimoku.senkou_b) if ichimoku.senkou_a and ichimoku.senkou_b else None
                    if cloud_bottom is None or current_price < cloud_bottom:
                        past_for_chikou = past_price_26 if past_price_26 else klines.iloc[-30]['close'] if len(klines) > 30 else None
                        if past_for_chikou and ichimoku.chikou_span and (ichimoku.chikou_span < past_for_chikou):
                            api.insert_order(SYMBOL, 'SELL', 'OPEN', LOT_SIZE, quote.bid_price1)
                            pass
                            position_side = -1
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
