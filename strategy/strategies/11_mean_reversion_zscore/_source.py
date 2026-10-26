# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import ma, std
SYMBOL = 'DCE.m2506'
ZSCORE_N = 20
ENTRY_Z = 2.0
EXIT_Z = 0.5
MAX_HOLD_BARS = 10
VOLUME = 1
KLINE_DURATION = 1800
DATA_LENGTH = 300

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=DATA_LENGTH)
    quote = api.get_quote(SYMBOL)
    pass
    pass
    hold_bars_count = 0
    last_signal_bar_index = -1
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            if api.is_changing(klines):
                close = klines['close']
                mean_n = ma(close, ZSCORE_N)
                std_n = std(close, ZSCORE_N)
                close_cur = close.iloc[-2]
                mean_cur = mean_n.iloc[-2]
                std_cur = std_n.iloc[-2]
                if std_cur == 0 or std_cur != std_cur:
                    pass
                    continue
                zscore = (close_cur - mean_cur) / std_cur
                pass
                position = api.get_position(SYMBOL)
                volume_long = position.volume_long
                volume_short = position.volume_short
                if volume_long > 0 or volume_short > 0:
                    hold_bars_count += 1
                else:
                    hold_bars_count = 0
                if volume_long > 0:
                    should_close_long = zscore > -EXIT_Z or hold_bars_count >= MAX_HOLD_BARS
                    if should_close_long:
                        target_pos.set_target_volume(0)
                        reason = '均值回归' if zscore > -EXIT_Z else '超时强制平仓'
                        pass
                        hold_bars_count = 0
                        continue
                if volume_short > 0:
                    should_close_short = zscore < EXIT_Z or hold_bars_count >= MAX_HOLD_BARS
                    if should_close_short:
                        target_pos.set_target_volume(0)
                        reason = '均值回归' if zscore < EXIT_Z else '超时强制平仓'
                        pass
                        hold_bars_count = 0
                        continue
                if volume_long == 0 and volume_short == 0:
                    if zscore < -ENTRY_Z:
                        target_pos.set_target_volume(VOLUME)
                        hold_bars_count = 0
                        pass
                    elif zscore > ENTRY_Z:
                        target_pos.set_target_volume(-VOLUME)
                        hold_bars_count = 0
                        pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
