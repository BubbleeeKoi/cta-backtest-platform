# Generated from the local original; see SOURCE_MANIFEST.json.
from .._source_compat import source_datetime
pass
from .._source_compat import TqApi, TqAuth, TqSim, TargetPosTask
import math
SYMBOL = 'CZCE.MA509'
GRID_LOW = 2200
GRID_HIGH = 2600
GRID_STEP = 40
VOLUME = 1
MAX_GRID_POSITION = 10
grid_lines = []
price = GRID_LOW
while price <= GRID_HIGH:
    grid_lines.append(round(price, 2))
    price += GRID_STEP
pass
pass
grid_has_position = {line: False for line in grid_lines}
last_price = None

def program(api):
    global last_price
    api = api
    quote = api.get_quote(SYMBOL)
    klines_1m = api.get_kline_serial(SYMBOL, 60, data_length=10)
    pass
    pass

    def get_grid_below(price, grid_lines):
        pass
        below = [g for g in grid_lines if g < price]
        return below[-1] if below else None

    def get_grid_above(price, grid_lines):
        pass
        above = [g for g in grid_lines if g > price]
        return above[0] if above else None
    try:
        target_pos = TargetPosTask(api, SYMBOL)
        while True:
            yield None
            position = api.get_position(SYMBOL)
            if api.is_changing(quote):
                current_price = quote.last_price
                if current_price != current_price or current_price <= 0:
                    continue
                if last_price is None:
                    last_price = current_price
                    pass
                    continue
                total_long = position.volume_long
                if current_price >= GRID_HIGH:
                    if total_long > 0:
                        target_pos.set_target_volume(0)
                        for line in grid_lines:
                            grid_has_position[line] = False
                        pass
                    last_price = current_price
                    continue
                for grid_price in grid_lines:
                    price_crossed_down = last_price > grid_price and current_price <= grid_price
                    price_crossed_up = last_price < grid_price and current_price >= grid_price
                    if price_crossed_down and (not grid_has_position[grid_price]):
                        if total_long < MAX_GRID_POSITION:
                            new_total_long = min(total_long + VOLUME, MAX_GRID_POSITION)
                            target_pos.set_target_volume(new_total_long)
                            grid_has_position[grid_price] = True
                            total_long = new_total_long
                            pass
                    if price_crossed_up:
                        grid_below = get_grid_below(grid_price, grid_lines)
                        if grid_below is not None and grid_has_position.get(grid_below, False):
                            new_total_long = max(total_long - VOLUME, 0)
                            target_pos.set_target_volume(new_total_long)
                            grid_has_position[grid_below] = False
                            total_long = new_total_long
                            profit_estimate = (grid_price - grid_below) * VOLUME
                            pass
                last_price = current_price
                active_grids = [g for g, has_pos in grid_has_position.items() if has_pos]
                if active_grids:
                    pass
    except KeyboardInterrupt:
        pass
    finally:
        api.close()
        pass
