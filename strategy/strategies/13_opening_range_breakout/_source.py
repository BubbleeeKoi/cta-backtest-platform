# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
from .._source_compat import hhv, llv
import datetime
SYMBOL = 'CFFEX.IF2506'
OPEN_RANGE_MINUTES = 30
OPEN_HOUR = 9
OPEN_MIN = 30
CLOSE_HOUR = 14
CLOSE_MIN = 45
STOP_LOSS_MULTIPLIER = 1.0
VOLUME = 1
KLINE_DURATION = 60
ORB_END_HOUR = OPEN_HOUR
ORB_END_MIN = OPEN_MIN + OPEN_RANGE_MINUTES
if ORB_END_MIN >= 60:
    ORB_END_HOUR += 1
    ORB_END_MIN -= 60

def program(api):
    api = api
    klines = api.get_kline_serial(SYMBOL, KLINE_DURATION, data_length=100)
    quote = api.get_quote(SYMBOL)
    pass
    pass
    orb_high = None
    orb_low = None
    orb_confirmed = False
    traded_today = False
    current_date = None
    stop_loss_price = None

    def reset_daily_state():
        pass
        nonlocal orb_high, orb_low, orb_confirmed, traded_today, stop_loss_price
        orb_high = None
        orb_low = None
        orb_confirmed = False
        traded_today = False
        stop_loss_price = None
        pass
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            position = api.get_position(SYMBOL)
            if api.is_changing(klines):
                bar_dt_ns = klines['datetime'].iloc[-2]
                bar_dt = source_datetime(bar_dt_ns / 1000000000.0)
                bar_date = bar_dt.date()
                bar_time = bar_dt.time()
                if current_date != bar_date:
                    current_date = bar_date
                    reset_daily_state()
                close_time = datetime.time(CLOSE_HOUR, CLOSE_MIN)
                if bar_time >= close_time:
                    if position.volume_long > 0:
                        target_pos.set_target_volume(0)
                        pass
                    if position.volume_short > 0:
                        target_pos.set_target_volume(0)
                        pass
                    continue
                open_time = datetime.time(OPEN_HOUR, OPEN_MIN)
                orb_end_time = datetime.time(ORB_END_HOUR, ORB_END_MIN)
                if open_time <= bar_time < orb_end_time:
                    bar_high = klines['high'].iloc[-2]
                    bar_low = klines['low'].iloc[-2]
                    if orb_high is None:
                        orb_high = bar_high
                        orb_low = bar_low
                    else:
                        orb_high = max(orb_high, bar_high)
                        orb_low = min(orb_low, bar_low)
                    pass
                elif bar_time >= orb_end_time and (not orb_confirmed):
                    if orb_high is not None and orb_low is not None:
                        orb_confirmed = True
                        orb_range = orb_high - orb_low
                        pass
                elif orb_confirmed and (not traded_today):
                    current_price = quote.last_price
                    if current_price <= 0 or current_price != current_price:
                        continue
                    orb_range = orb_high - orb_low
                    stop_dist = orb_range * STOP_LOSS_MULTIPLIER
                    if stop_loss_price is not None:
                        if position.volume_long > 0 and current_price < stop_loss_price:
                            target_pos.set_target_volume(0)
                            pass
                            traded_today = True
                            continue
                        if position.volume_short > 0 and current_price > stop_loss_price:
                            target_pos.set_target_volume(0)
                            pass
                            traded_today = True
                            continue
                    if position.volume_long == 0 and position.volume_short == 0:
                        if current_price > orb_high:
                            target_pos.set_target_volume(VOLUME)
                            stop_loss_price = current_price - stop_dist
                            traded_today = True
                            pass
                        elif current_price < orb_low:
                            target_pos.set_target_volume(-VOLUME)
                            stop_loss_price = current_price + stop_dist
                            traded_today = True
                            pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
