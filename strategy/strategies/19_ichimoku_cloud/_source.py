# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import max as tq_max, min as tq_min
SYMBOL = 'SHFE.rb2505'
TENKAN_PERIOD = 9
KIJUN_PERIOD = 26
SENKOU_PERIOD = 52
KLINE_DUR = 3600
VOLUME = 5

def calculate_ichimoku(kline, tenkan_period, kijun_period, senkou_period):
    pass
    high = list(kline['high'])
    low = list(kline['low'])
    close = list(kline['close'])
    if len(high) < kijun_period + senkou_period:
        return (None, None, None, None)
    tenkan = (tq_max(high[-tenkan_period:], tenkan_period) + tq_min(low[-tenkan_period:], tenkan_period)) / 2
    kijun = (tq_max(high[-kijun_period:], kijun_period) + tq_min(low[-kijun_period:], kijun_period)) / 2
    senkou_a = (tenkan + kijun) / 2
    senkou_b = (tq_max(high[-senkou_period:], senkou_period) + tq_min(low[-senkou_period:], senkou_period)) / 2
    return (tenkan, kijun, senkou_a, senkou_b)

def program(api):
    api = api
    kline = api.get_kline_serial(SYMBOL, KLINE_DUR)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    prev_kijun = None
    prev_tenkan = None
    while True:
        yield None
        if len(kline) < KIJUN_PERIOD + SENKOU_PERIOD:
            continue
        tenkan, kijun, senkou_a, senkou_b = calculate_ichimoku(kline, TENKAN_PERIOD, KIJUN_PERIOD, SENKOU_PERIOD)
        if tenkan is None or kijun is None:
            continue
        current_price = list(kline['close'])[-1]
        if prev_tenkan and prev_kijun:
            if prev_tenkan <= prev_kijun and tenkan > kijun:
                target_pos.set_target_volume(VOLUME)
                pass
            elif prev_tenkan >= prev_kijun and tenkan < kijun:
                target_pos.set_target_volume(-VOLUME)
                pass
        prev_tenkan = tenkan
        prev_kijun = kijun
