"""Exact single-symbol feature functions from the original TqSdk factor examples."""
from __future__ import annotations
import numpy as np
import pandas as pd
from collections import deque

from ._legacy import LegacyIndicatorStrategy
EPS = 1e-12
ENTRY_SCORE = 0.85
EXIT_SCORE = 0.25
BASE_VOLUME = 1
MAX_VOLUME = 1

def latest(series, default=0.0):
    try:
        value = series.iloc[-1]
    except Exception:
        return default
    if pd.isna(value) or np.isinf(value):
        return default
    return float(value)


def clamp(value, lower=-3.0, upper=3.0):
    return max(lower, min(upper, float(value)))


def rolling_zscore(series, window=40):
    if len(series) < window + 2:
        return 0.0
    sample = series.iloc[-window:]
    std = sample.std()
    if pd.isna(std) or std < EPS:
        return 0.0
    return latest((series - sample.mean()) / std)


def calc_atr(df, period=14):
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def calc_rsi(close, period=14):
    diff = close.diff()
    up = diff.clip(lower=0).rolling(period).mean()
    down = (-diff.clip(upper=0)).rolling(period).mean()
    rs = up / (down + EPS)
    return 100 - 100 / (1 + rs)


def calc_mfi(df, period=14):
    typical = (df["high"] + df["low"] + df["close"]) / 3
    raw_money = typical * df["volume"].replace(0, np.nan).fillna(0)
    direction = typical.diff()
    positive = raw_money.where(direction > 0, 0.0).rolling(period).sum()
    negative = raw_money.where(direction < 0, 0.0).rolling(period).sum().abs()
    ratio = positive / (negative + EPS)
    return 100 - 100 / (1 + ratio)


def calc_kama(close, er_period=10, fast=2, slow=30):
    if len(close) < slow + er_period + 2:
        return close.rolling(slow).mean()
    change = (close - close.shift(er_period)).abs()
    volatility = close.diff().abs().rolling(er_period).sum()
    er = (change / (volatility + EPS)).fillna(0)
    fast_sc = 2 / (fast + 1)
    slow_sc = 2 / (slow + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
    kama = close.copy().astype(float)
    kama.iloc[:slow] = close.iloc[:slow].mean()
    for i in range(slow, len(close)):
        kama.iloc[i] = kama.iloc[i - 1] + sc.iloc[i] * (close.iloc[i] - kama.iloc[i - 1])
    return kama


def calc_nvi(close, volume):
    nvi = pd.Series(1000.0, index=close.index)
    returns = close.pct_change().fillna(0)
    for i in range(1, len(close)):
        if volume.iloc[i] < volume.iloc[i - 1]:
            nvi.iloc[i] = nvi.iloc[i - 1] * (1 + returns.iloc[i])
        else:
            nvi.iloc[i] = nvi.iloc[i - 1]
    return nvi


def open_interest_series(df):
    for field in ("close_oi", "open_oi", "open_interest", "interest"):
        if field in df.columns:
            return df[field].astype(float)
    return pd.Series(0.0, index=df.index)


def calculate_features(df):
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float).replace(0, np.nan).ffill().fillna(0)
    oi = open_interest_series(df)
    atr = calc_atr(df)
    rsi = calc_rsi(close)
    mfi = calc_mfi(df)
    ma_fast = close.rolling(10).mean()
    ma_slow = close.rolling(30).mean()
    kama = calc_kama(close)
    returns = close.pct_change().fillna(0)
    vol_20 = returns.rolling(20).std()
    high_20 = high.rolling(20).max().shift(1)
    low_20 = low.rolling(20).min().shift(1)
    range_20 = (high_20 - low_20).replace(0, np.nan)
    mid_40 = close.rolling(40).mean()
    std_40 = close.rolling(40).std()
    boll_upper = mid_40 + 2 * std_40
    boll_lower = mid_40 - 2 * std_40
    percent_b = (close - boll_lower) / (boll_upper - boll_lower + EPS)
    typical = (high + low + close) / 3
    vwap = (typical * volume).rolling(30).sum() / (volume.rolling(30).sum() + EPS)
    nvi = calc_nvi(close, volume)
    efficiency = (close.diff(10).abs() / (close.diff().abs().rolling(10).sum() + EPS)).fillna(0)
    path_ratio = (high.rolling(20).max() - low.rolling(20).min()) / (close.diff().abs().rolling(20).sum() + EPS)
    drawdown = close / (close.rolling(40).max() + EPS) - 1
    runup = close / (close.rolling(40).min() + EPS) - 1
    atr_now = latest(atr, 0.0)
    price = latest(close, 0.0)
    atr_pct = atr_now / max(price, EPS)
    avg_atr_pct = latest((atr / (close + EPS)).rolling(60).mean())
    volume_ratio = latest(volume / (volume.rolling(20).mean() + EPS) - 1)
    channel_high = latest(high_20)
    channel_low = latest(low_20)
    short_high = latest(high.rolling(6).max().shift(1))
    short_low = latest(low.rolling(6).min().shift(1))
    close_sign_10 = np.sign(latest(close.diff(10), 0))
    rsi_sign_10 = np.sign(latest(rsi.diff(10), 0))

    features = {
        "momentum_5": clamp(latest(close.pct_change(5)) * 20),
        "momentum_20": clamp(latest(close.pct_change(20)) * 10),
        "trend_slope": clamp((latest(ma_fast) - latest(ma_slow)) / max(price, EPS) * 30),
        "kama_trend": clamp((price - latest(kama)) / max(atr_now, EPS)),
        "efficiency": clamp(latest(efficiency) * np.sign(latest(close.diff(10))) * 2),
        "volatility_filter": clamp(-(atr_pct - avg_atr_pct) * 100),
        "fractal_trend": clamp((latest(path_ratio) - 0.45) * 3),
        "range_breakout": clamp((price - channel_high) / max(atr_now, EPS)) if price > channel_high else clamp((price - channel_low) / max(atr_now, EPS)) if price < channel_low else 0.0,
        "volume_confirm": clamp(volume_ratio),
        "cmo": clamp((returns.tail(14).clip(lower=0).sum() + returns.tail(14).clip(upper=0).sum()) / (returns.tail(14).abs().sum() + EPS) * 2),
        "squeeze_breakout": clamp((1 if latest(std_40 / (mid_40 + EPS)) < latest((std_40 / (mid_40 + EPS)).rolling(80).quantile(0.25)) else 0) * latest(np.sign(close.diff(5))) * abs(volume_ratio + 1)),
        "range_expansion": clamp((latest(high - low) / max(latest(atr), EPS) - 1) * np.sign(latest(close.diff()))),
        "atr_position": clamp((price - latest(close.rolling(20).mean())) / max(atr_now, EPS)),
        "vwap_reversion": clamp(-(price - latest(vwap)) / max(atr_now, EPS)),
        "rsi_reversal": clamp((50 - latest(rsi, 50)) / 18),
        "divergence": clamp(-close_sign_10 if close_sign_10 != rsi_sign_10 else 0),
        "mean_reversion": clamp(-rolling_zscore(close, 40)),
        "boll_reversion": clamp((0.5 - latest(percent_b, 0.5)) * 3),
        "volatility_decline": clamp((avg_atr_pct - atr_pct) * 80),
        "range_reversion": clamp((0.5 - latest((close - low_20) / (range_20 + EPS), 0.5)) * 2),
        "atr_zscore_reversion": clamp(-(price - latest(mid_40)) / max(atr_now, EPS)),
        "mfi_reversal": clamp((50 - latest(mfi, 50)) / 18),
        "price_volume_divergence": clamp(-np.sign(latest(close.diff(5))) if volume_ratio < -0.2 else 0),
        "value_area_reversion": clamp(-(price - latest((typical * volume).rolling(60).sum() / (volume.rolling(60).sum() + EPS))) / max(atr_now, EPS)),
        "oi_momentum": clamp(latest(oi.pct_change(5)) * 20 * np.sign(latest(close.pct_change(5), 0))),
        "turnover_breakout": clamp(volume_ratio * np.sign(latest(close.diff(5), 0))),
        "nvi_trend": clamp((latest(nvi) - latest(nvi.rolling(30).mean())) / (latest(nvi.rolling(30).std()) + EPS)),
        "risk_adjusted_momentum": clamp(latest(close.pct_change(20)) / (latest(vol_20) + EPS) / 3),
        "low_volatility": clamp((latest(vol_20.rolling(60).mean()) - latest(vol_20)) * 20),
        "liquidity": clamp(np.log1p(latest(volume.rolling(20).mean())) / 12 - 0.5),
        "carry_proxy": clamp((latest(ma_fast) - latest(ma_slow)) / max(price, EPS) * 20),
        "term_structure_proxy": clamp((latest(close.pct_change(60)) - latest(close.pct_change(20))) * 8),
        "regime_trend": clamp((abs(latest(ma_fast - ma_slow)) / max(atr_now, EPS) - 0.3) * np.sign(latest(ma_fast - ma_slow))),
        "opening_range_breakout": clamp((price - short_high) / max(atr_now, EPS)) if price > short_high else clamp((price - short_low) / max(atr_now, EPS)) if price < short_low else 0.0,
        "vol_target": clamp(0.015 / max(atr_pct, 0.003) - 1),
        "drawdown_guard": clamp((latest(runup) + latest(drawdown)) * 2),
    }
    return features


def weighted_score(features, weights):
    score = 0.0
    detail = []
    for name, weight in weights.items():
        value = features.get(name, 0.0)
        score += weight * value
        detail.append(f"{name}={value:.2f}")
    return clamp(score), ", ".join(detail)


def score_to_volume(score):
    if abs(score) < EXIT_SCORE:
        return 0
    if abs(score) < ENTRY_SCORE:
        return None
    volume = min(MAX_VOLUME, max(1, int(abs(score) // ENTRY_SCORE) + BASE_VOLUME - 1))
    return volume if score > 0 else -volume


class FactorStrategy(LegacyIndicatorStrategy):
    """Run the original weighted single-symbol rule on completed selected bars."""

    FACTOR_WEIGHTS: dict[str, float] = {}
    ENTRY_SCORE = 0.85
    EXIT_SCORE = 0.25

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        # Every original single-symbol factor script requests DATA_LENGTH=180.
        # Recursive KAMA depends on the first observation in that window.
        self._source_bars: deque[dict[str, float]] = deque(maxlen=180)

    def _add(self, bar):
        # HDF5Daily0905Source emits a 09:05 execution row and then a row
        # containing the *entire* trading day's OHLCV. Do not sum them.
        timestamp = pd.Timestamp(bar.timestamp)
        if (self.timeframe == "1d" and self.params.get("_daily_event_source", True)
                and (timestamp.hour, timestamp.minute) != (9, 5)):
            self._bucket = {
                "open": float(bar.open), "high": float(bar.high),
                "low": float(bar.low), "close": float(bar.close),
                "volume": float(bar.volume), "oi": float(bar.oi),
                "tradingday": pd.Timestamp(bar.tradingday).normalize(),
            }
            return
        super()._add(bar)

    def _indicator_signal(self):
        if self._bucket is None:
            return None
        self._source_bars.append(dict(self._bucket))
        if len(self._source_bars) < 180:
            return None
        frame = pd.DataFrame(self._source_bars)
        frame["close_oi"] = frame["oi"]
        features = calculate_features(frame)
        score, _ = weighted_score(features, self.FACTOR_WEIGHTS)
        if abs(score) < self.EXIT_SCORE:
            return 0
        if abs(score) < self.ENTRY_SCORE:
            return None
        return 1 if score > 0 else -1
