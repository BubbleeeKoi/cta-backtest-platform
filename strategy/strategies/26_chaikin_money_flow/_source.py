# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
import pandas as pd
SYMBOL = 'SHFE.cu2506'
CMF_N = 20
VOLUME = 1
BULL_TH = 0.05
BEAR_TH = -0.05

def calc_cmf(klines: pd.DataFrame, n: int) -> pd.Series:
    pass
    high = klines['high']
    low = klines['low']
    close = klines['close']
    volume = klines['volume']
    hl_range = high - low
    hl_range = hl_range.replace(0, float('nan'))
    mfm = (2 * close - high - low) / hl_range
    mfv = mfm * volume
    cmf = mfv.rolling(n).sum() / volume.rolling(n).sum()
    return cmf

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, 86400, data_length=CMF_N + 10)
    target_pos = TargetPosTask(api, SYMBOL)
    prev_cmf = None
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        cmf_series = calc_cmf(klines, CMF_N)
        current_cmf = cmf_series.iloc[-2]
        if pd.isna(current_cmf):
            pass
            prev_cmf = current_cmf
            continue
        pass
        if prev_cmf is not None and (not pd.isna(prev_cmf)):
            if prev_cmf <= BULL_TH and current_cmf > BULL_TH:
                pass
                target_pos.set_target_volume(VOLUME)
            elif prev_cmf >= BEAR_TH and current_cmf < BEAR_TH:
                pass
                target_pos.set_target_volume(-VOLUME)
            elif prev_cmf >= 0 and current_cmf < 0:
                pass
                target_pos.set_target_volume(0)
            elif prev_cmf <= 0 and current_cmf > 0:
                pass
                target_pos.set_target_volume(0)
        prev_cmf = current_cmf
    api.close()
