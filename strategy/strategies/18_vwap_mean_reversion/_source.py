# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import std, mean
SYMBOL = 'SHFE.rb2505'
VWAP_PERIOD = 20
DEVIATION = 0.5
KLINE_DUR = 300
VOLUME = 5

def calculate_vwap(close_list, vol_list, period):
    pass
    if len(close_list) < period:
        return None
    recent_close = close_list[-period:]
    recent_vol = vol_list[-period:]
    if sum(recent_vol) <= 0:
        return None
    vwap = sum((c * v for c, v in zip(recent_close, recent_vol))) / sum(recent_vol)
    return vwap

def program(api):
    api = api
    kline = api.get_kline_serial(SYMBOL, KLINE_DUR)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    pass
    while True:
        yield None
        if len(kline) < VWAP_PERIOD + 1:
            continue
        close_list = list(kline['close'])
        vol_list = list(kline['volume'])
        vwap = calculate_vwap(close_list, vol_list, VWAP_PERIOD)
        if vwap is None:
            continue
        current_price = close_list[-1]
        deviation_pct = (current_price - vwap) / vwap * 100
        if deviation_pct > DEVIATION:
            target_pos.set_target_volume(-VOLUME)
            pass
        elif deviation_pct < -DEVIATION:
            target_pos.set_target_volume(VOLUME)
            pass
        elif abs(deviation_pct) < DEVIATION / 2:
            target_pos.set_target_volume(0)
            pass
