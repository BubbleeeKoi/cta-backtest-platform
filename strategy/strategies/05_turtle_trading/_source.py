# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
import pandas as pd
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'INE.sc2501'
N1 = 20
N2 = 10
ATR_PERIOD = 20
RISK_RATIO = 0.01
CONTRACT_MULTIPLIER = 1000
MAX_VOLUME = 10
KLINE_DUR = 86400

def calc_atr(klines: pd.DataFrame, period: int) -> pd.Series:
    pass
    high, low, close = (klines.high, klines.low, klines.close)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()

def calc_volume(account, atr_val: float) -> int:
    pass
    if atr_val <= 0:
        return 1
    vol = int(account.balance * RISK_RATIO / (atr_val * CONTRACT_MULTIPLIER))
    return max(1, min(vol, MAX_VOLUME))

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DUR, data_length=N1 + 5)
    account = api.get_account()
    target_pos = TargetPosTask(api, SYMBOL)
    pass
    while True:
        yield None
        if not api.is_changing(klines):
            continue
        atr_val = calc_atr(klines, ATR_PERIOD).iloc[-1]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        high_n1 = klines.high.iloc[-(N1 + 1):-1].max()
        low_n1 = klines.low.iloc[-(N1 + 1):-1].min()
        high_n2 = klines.high.iloc[-(N2 + 1):-1].max()
        low_n2 = klines.low.iloc[-(N2 + 1):-1].min()
        last_close = klines.close.iloc[-2]
        vol = calc_volume(account, atr_val)
        pass
        if last_close > high_n1:
            pass
            target_pos.set_target_volume(vol)
        elif last_close < low_n1:
            pass
            target_pos.set_target_volume(-vol)
        elif last_close < low_n2:
            pass
            target_pos.set_target_volume(0)
        elif last_close > high_n2:
            pass
            target_pos.set_target_volume(0)
    api.close()
