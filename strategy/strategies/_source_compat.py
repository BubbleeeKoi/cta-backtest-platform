"""Offline numerical/transport compatibility used by generated source rules.

This module never opens a network connection or submits a broker order.
Source scripts mix Series and DataFrame spellings of indicator APIs. Accept
both and expose their requested column aliases without changing thresholds.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import numpy as np
import pandas as pd


def source_datetime(value, tz=None):
    # The local HDF5 timestamps are naive Shanghai wall times. Decode them
    # consistently even when the execution host uses another timezone.
    stamp = datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
    return stamp.replace(tzinfo=tz) if tz is not None else stamp


def _series(value):
    if isinstance(value, pd.DataFrame):
        return value.close
    return value if isinstance(value, pd.Series) else pd.Series(value, dtype=float)


def ma(value, n):
    return _series(value).rolling(n).mean()


mean = ma
MA = ma


def ema(value, n):
    return _series(value).ewm(span=n, adjust=False).mean()


def sma(value, n, m=1):
    return _series(value).ewm(alpha=m/n, adjust=False).mean()


def std(value, n):
    # tqsdk.tafunc.std and tqsdk.ta.BOLL use pandas' sample deviation.
    return _series(value).rolling(n).std(ddof=1)


def hhv(value, n):
    return _series(value).rolling(n).max()


def llv(value, n):
    return _series(value).rolling(n).min()


def crossup(a, b):
    return (a > b) & (a.shift() <= (b.shift() if isinstance(b, pd.Series) else b))


def crossdown(a, b):
    return (a < b) & (a.shift() >= (b.shift() if isinstance(b, pd.Series) else b))


def max(value, n):
    # Source 19 imports rolling max/min but passes a sliced Python list and
    # consumes a scalar. Normalize that invalid SDK call to its window extreme.
    return float(np.max(value[-n:]))


def min(value, n):
    return float(np.min(value[-n:]))


def _tr(frame):
    previous = frame.close.shift()
    span = frame.high-frame.low
    up, down = (frame.high-previous).abs(), (frame.low-previous).abs()
    # Follow the SDK's comparisons, including its NaN at the first row.
    peak = np.where(span > up, span, up)
    return pd.Series(np.where(peak > down, peak, down), index=frame.index)


def ATR(frame, n=14):
    return _tr(frame).rolling(n).mean()


def atr(*args):
    if isinstance(args[0], pd.DataFrame):
        return ATR(*args)
    high, low, close, n = args
    frame = pd.DataFrame(dict(high=high, low=low, close=close))
    return ATR(frame, n).to_numpy()


def dx(high, low, close, n):
    high, low, close = map(_series, (high, low, close))
    up, down = high.diff(), -low.diff()
    plus = up.where((up > down) & (up > 0), 0).rolling(n).sum()
    minus = down.where((down > up) & (down > 0), 0).rolling(n).sum()
    return (plus-minus).abs() / (plus+minus).replace(0, np.nan) * 100


def BOLL(value, period=20, std_multiplier=2):
    close = _series(value)
    middle = ma(close, period)
    spread = std(close, period) * std_multiplier
    return pd.DataFrame(dict(mid=middle, middle=middle, upp=middle+spread,
                             upper=middle+spread, top=middle+spread,
                             low=middle-spread, lower=middle-spread,
                             bottom=middle-spread))


def RSI(value, n=14):
    change = _series(value).diff()
    positive = pd.Series(np.where(change > 0, change, 0), index=change.index)
    return sma(positive, n) / sma(change.abs(), n) * 100


class BacktestFinished(Exception):
    pass


def _unused(*args, **kwargs):
    return None


TqAuth = TqSim = TqBacktest = TqAccount = _unused


def TqApi(*args, **kwargs):
    raise RuntimeError("Live TqApi is unavailable in offline source programs")


class TargetPosTask:
    def __init__(self, api, symbol):
        self.api = api
        self.target = 0

    def set_target_volume(self, target):
        self.target = int(target)
        self.api.desired_target = int(target)
        self.api.target = int(target)

    def get_target_volume(self):
        return self.target


class OfflineAPI:
    """Mutable source serials and filled positions, not a simulated broker."""

    def __init__(self):
        self.serials = []
        self.target = None
        self.desired_target = None
        self.quote = SimpleNamespace(datetime="", last_price=np.nan, open=np.nan,
                                     bid_price1=np.nan, ask_price1=np.nan)
        self.position = SimpleNamespace(volume_long=0, volume_short=0,
                                        pos_long=0, pos_short=0,
                                        pos_long_today=0, pos_short_today=0)
        self.net = 0
        self.changed = set()
        self.changed_stamps = set()

    def get_kline_serial(self, symbol, duration_seconds, data_length=200):
        if duration_seconds <= 0 or data_length < 2:
            raise ValueError("Source duration must be positive and serial length at least 2")
        frame = pd.DataFrame(columns=["datetime", "id", "open", "high", "low",
                                      "close", "volume", "close_oi", "open_oi"])
        self.serials.append((int(duration_seconds), int(data_length), frame))
        return frame

    def get_quote(self, symbol):
        return self.quote

    def get_position(self, symbol):
        return self.position

    def get_account(self):
        return SimpleNamespace(balance=200000, available=200000, max_drawdown=0)

    def is_changing(self, obj, *fields):
        if isinstance(obj, pd.DataFrame):
            return id(obj) in self.changed
        if isinstance(obj, pd.Series) and "datetime" in obj:
            return obj["datetime"] in self.changed_stamps
        return True

    def insert_order(self, symbol=None, direction=None, offset=None, volume=1,
                     limit_price=None, **kwargs):
        sign = 1 if direction == "BUY" else -1
        base = self.net if self.target is None else self.target
        if offset.startswith("CLOSE"):
            self.target = base + sign * builtins_min(abs(base), int(volume))
        else:
            self.target = base + sign * int(volume)
        return SimpleNamespace(status="FINISHED")

    def sync_position(self, net):
        self.net = int(net)
        long, short = builtins_max(self.net, 0), builtins_max(-self.net, 0)
        self.position.volume_long = self.position.pos_long = long
        self.position.volume_short = self.position.pos_short = short

    def register_update_notify(self):
        from contextlib import nullcontext
        return nullcontext()

    def close(self):
        pass


from builtins import min as builtins_min, max as builtins_max
