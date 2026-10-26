# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from datetime import time
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
SYMBOL = 'SHFE.cu2501'
N_DAYS = 4
K1 = 0.5
K2 = 0.5
VOLUME = 1
CLOSE_HOUR = 14
CLOSE_MINUTE = 50

def program(api):
    api = api
    daily_klines = api.get_kline_serial(SYMBOL, 86400, data_length=N_DAYS + 2)
    quote = api.get_quote(SYMBOL)
    target_pos = TargetPosTask(api, SYMBOL)
    today_date = None
    buy_line = sell_line = None
    pass
    while True:
        yield None
        if not quote.datetime:
            continue
        current_date = quote.datetime[:10]
        if current_date != today_date:
            today_date = current_date
            today_open = quote.open
            hist_high = daily_klines.high.iloc[-(N_DAYS + 1):-1]
            hist_low = daily_klines.low.iloc[-(N_DAYS + 1):-1]
            hist_close = daily_klines.close.iloc[-(N_DAYS + 1):-1]
            hh = hist_high.max()
            ll = hist_low.min()
            lc = hist_close.min()
            hc = hist_close.max()
            price_range = max(hh - lc, hc - ll)
            buy_line = today_open + K1 * price_range
            sell_line = today_open - K2 * price_range
            pass
        if buy_line is None:
            continue
        last_price = quote.last_price
        t = time(*[int(x) for x in quote.datetime[11:19].split(':')])
        if t >= time(CLOSE_HOUR, CLOSE_MINUTE):
            target_pos.set_target_volume(0)
            continue
        if last_price > buy_line:
            target_pos.set_target_volume(VOLUME)
        elif last_price < sell_line:
            target_pos.set_target_volume(-VOLUME)
    api.close()
