"""Original signal rules for the early trend and reversion examples."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cross_up(a, b):
    return a.iloc[-2] <= b.iloc[-2] and a.iloc[-1] > b.iloc[-1]


def _cross_down(a, b):
    return a.iloc[-2] >= b.iloc[-2] and a.iloc[-1] < b.iloc[-1]


def _16(strategy, frame):
    period = 25
    if len(frame) < period + 2:
        return None
    high, low = frame.high, frame.low
    up = high.rolling(period + 1).apply(lambda x: np.argmax(x) / period * 100, raw=True)
    down = low.rolling(period + 1).apply(lambda x: np.argmin(x) / period * 100, raw=True)
    if _cross_up(up, down) and up.iloc[-1] > 70:
        return 1
    if _cross_up(down, up) and down.iloc[-1] > 70:
        return -1
    return None


def _17(strategy, frame):
    if len(frame) < 35:
        return None
    close = frame.close
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / (loss + 1e-10))
    lo, hi = rsi.rolling(14).min(), rsi.rolling(14).max()
    k = ((rsi - lo) / (hi - lo).replace(0, np.nan)).rolling(3).mean()
    d = k.rolling(3).mean()
    if _cross_up(k, d) and k.iloc[-1] < .2:
        return 1
    if _cross_down(k, d) and k.iloc[-1] > .8:
        return -1
    if k.iloc[-1] > .8 or k.iloc[-1] < .2:
        return 0
    return None


def _18_boll(strategy, frame):
    if len(frame) < 20:
        return None
    close = frame.close
    middle = close.rolling(20).mean().iloc[-1]
    std = close.rolling(20).std().iloc[-1]
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    loss = (-diff).clip(lower=0).ewm(alpha=1/14, adjust=False).mean().iloc[-1]
    rsi = 100 - 100 / (1 + gain / (loss + 1e-10))
    price = close.iloc[-1]
    if price <= middle - 2 * std and rsi < 30:
        return 1
    if price >= middle + 2 * std and rsi > 70:
        return -1
    if price >= middle and strategy.position.net_volume > 0:
        return 0
    if price <= middle and strategy.position.net_volume < 0:
        return 0
    return None


def _18_vwap(strategy, frame):
    if len(frame) < 21:
        return None
    sample = frame.iloc[-20:]
    volume = sample.volume.sum()
    if volume == 0:
        return None
    vwap = (sample.close * sample.volume).sum() / volume
    deviation = (frame.close.iloc[-1] - vwap) / vwap * 100
    if deviation > .5:
        return -1
    if deviation < -.5:
        return 1
    if abs(deviation) < .25:
        return 0
    return None


def _19_wr(strategy, frame):
    if len(frame) < 21:
        return None
    highest = frame.high.rolling(14).max()
    lowest = frame.low.rolling(14).min()
    wr = (highest - frame.close) / (highest - lowest).replace(0, np.nan) * -100
    prior, now = wr.iloc[-2], wr.iloc[-1]
    ma = frame.close.rolling(20).mean()
    trend_up = ma.iloc[-1] > ma.iloc[-2]
    if prior < -80 and now >= -80 and trend_up:
        return 1
    if prior > -20 and now <= -20 and not trend_up:
        return -1
    if (prior <= -20 and now > -20) or (prior >= -80 and now < -80):
        return 0
    return None


def _19_cloud(strategy, frame):
    if len(frame) < 78:
        return None
    high, low = frame.high, frame.low
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2
    if _cross_up(tenkan, kijun):
        return 1
    if _cross_down(tenkan, kijun):
        return -1
    return None


def _wma(series, period):
    weight = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda x: np.dot(x, weight) / weight.sum(), raw=True)


def _20(strategy, frame):
    if len(frame) < 26:
        return None
    period = 20
    half, root = max(period // 2, 2), max(int(np.sqrt(period)), 2)
    hma = _wma(2 * _wma(frame.close, half) - _wma(frame.close, period), root)
    now, prior, older = hma.iloc[-1], hma.iloc[-2], hma.iloc[-3]
    rising = now > prior
    if rising and prior < older:
        return 1
    if not rising and prior > older:
        return -1
    return 0


def _21(strategy, frame):
    if len(frame) < 22:
        return None
    close = frame.close
    middle = close.ewm(span=20, adjust=False).mean()
    previous = close.shift()
    tr = pd.concat((frame.high-frame.low, (frame.high-previous).abs(),
                    (frame.low-previous).abs()), axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/10, adjust=False).mean()
    upper, lower = middle + 2 * atr, middle - 2 * atr
    if _cross_up(close, upper):
        return 1
    if _cross_down(close, lower):
        return -1
    return 0


def _22(strategy, frame):
    if len(frame) < 40:
        return None
    close = frame.close
    ema3 = close.ewm(span=12, adjust=False).mean().ewm(span=12, adjust=False).mean().ewm(span=12, adjust=False).mean()
    trix = ema3.pct_change() * 100
    signal = trix.rolling(9).mean()
    up, down = _cross_up(trix, signal), _cross_down(trix, signal)
    now, prior = trix.iloc[-1], trix.iloc[-2]
    if (up and now > 0) or (prior < 0 <= now):
        return 1
    if (down and now < 0) or (prior > 0 >= now):
        return -1
    if up or down:
        return 0
    return None


RULES = {
    "16_aroon_trend": _16,
    "17_stochastic_rsi": _17,
    "18_bollinger_mean_reversion": _18_boll,
    "18_vwap_mean_reversion": _18_vwap,
    "19_williams_r": _19_wr,
    "19_ichimoku_cloud": _19_cloud,
    "20_hull_ma": _20,
    "21_keltner_channel": _21,
    "22_trix_trend": _22,
}
