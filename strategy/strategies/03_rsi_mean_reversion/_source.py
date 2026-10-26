# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'CZCE.MA501'
RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
KLINE_DUR = 60 * 15
VOLUME = 1

def calc_rsi(close_series: pd.Series, period: int) -> pd.Series:
    pass
    delta = close_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, float('inf'))
    return 100 - 100 / (1 + rs)

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=RSI_PERIOD * 3)
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        rsi_series = calc_rsi(klines.close, RSI_PERIOD)
        rsi = rsi_series.iloc[-1]
        if pd.isna(rsi):
            continue
        pass
        if rsi < OVERSOLD:
            pass
            target_pos.set_target_volume(VOLUME)
        elif rsi > OVERBOUGHT:
            pass
            target_pos.set_target_volume(-VOLUME)
        elif 40 < rsi < 60:
            pass
            target_pos.set_target_volume(0)
    api.close()
