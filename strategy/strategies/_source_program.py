"""Execute source decision programs on completed local bars only."""
from __future__ import annotations

from collections import deque
from functools import lru_cache
from pathlib import Path
from numbers import Real
import numpy as np
import pandas as pd

from ._legacy import LegacyIndicatorStrategy
from ._source_compat import OfflineAPI


# These originals explicitly read the penultimate serial observation. The
# final row is a zero-volume execution sentinel, not an unseen future candle.
PREVIOUS = {
    "05_turtle_trading", "06_macd_trend", "07_kdj_signal", "08_cci_breakout",
    "09_atr_stop_loss", "10_momentum_breakout", "11_mean_reversion_zscore",
    "13_opening_range_breakout", "14_volume_price_trend", "15_donchian_channel",
    "26_chaikin_money_flow", "30_supertrend", "31_vwap_mean_reversion",
    "32_ichimoku_cloud", "32_linear_regression_channel", "25_multiperiod_ma",
}
TIMEFRAMES = {"15m": 900, "1h": 3600, "1d": 86400}


@lru_cache(maxsize=100)
def _code(name):
    path = Path(__file__).parent / name / "_source.py"
    return compile(path.read_text(encoding="utf-8"), str(path), "exec")


class SourceProgramStrategy(LegacyIndicatorStrategy):
    """Keep each source's formulas, branches and local state in its own program."""

    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        super().__init__(strategy_id, contract_info, data_pool, params)
        self.source_name = type(self).__module__.split(".")[-2]
        self._api = OfflineAPI()
        namespace = {"__name__": f"strategies.{self.source_name}._source",
                     "__package__": f"strategies.{self.source_name}"}
        exec(_code(self.source_name), namespace)
        for key in ("KLINE_DUR", "KLINE_DURATION", "KLINE_FREQ", "KLINE_PERIOD", "TRADE_DURATION"):
            if key in namespace:
                namespace[key] = TIMEFRAMES[self.timeframe]
        namespace["SYMBOL"] = self.symbol
        namespace["SYMBOLS"] = [self.symbol]
        # Explicit source constants are overrideable without generic fast/slow
        # parameters silently changing an unrelated indicator.
        for key, value in self.params.get("source_params", {}).items():
            if key not in namespace or not key.isupper():
                raise ValueError(f"Unknown source constant: {key}")
            namespace[key] = value
        if self.source_name == "12_grid_trading":
            namespace["VOLUME"] = self.volume
        if self.source_name == "13_opening_range_breakout":
            # Retain the original top-level minute carry when source constants
            # are overridden after loading the program.
            hour, minute = divmod(namespace["OPEN_HOUR"]*60 + namespace["OPEN_MIN"]
                                  + namespace["OPEN_RANGE_MINUTES"], 60)
            namespace["ORB_END_HOUR"], namespace["ORB_END_MIN"] = hour, minute
        self._program = namespace["program"](self._api)
        next(self._program)
        self._streams = []
        for stream_index, (source_duration, length, frame) in enumerate(self._api.serials):
            duration = source_duration
            # The two class examples hard-code a 60-second subscription.
            if self.source_name in {"12_grid_trading", "26_chaikin_money_flow", "34_vwap_breakout", "35_fibonacci_retracement"}:
                duration = TIMEFRAMES[self.timeframe]
            previous = self.source_name in PREVIOUS
            if self.source_name == "04_dual_thrust":
                previous = True
            elif self.source_name in {"23_pivot_point", "24_r_breaker"}:
                # At a daily close both subscriptions contain today's completed
                # bar: source [-2] is yesterday, source [-1] is today. Intraday
                # reference streams need a sentinel for the forming daily bar.
                previous = stream_index == 0 and self.timeframe != "1d"
            if self.source_name == "25_multiperiod_ma" and source_duration == 900:
                duration = TIMEFRAMES[self.timeframe]
            self._streams.append(dict(duration=duration, length=length,
                                      previous=previous, frame=frame,
                                      history=deque(maxlen=length), key=None, bucket=None))
        self._clock = dict(duration=TIMEFRAMES[self.timeframe], key=None, bucket=None)
        self._source_namespace = namespace
        self._day_open = None
        self._trading_day = None

    def on_init(self, history):
        """Prefill source serials from observations strictly before the run.

        The source subscriptions start with history already present. Warm-up
        loads indicator windows without placing fictional pre-start trades.
        """
        available = history.own_bars
        if available is None or available.empty:
            return
        cutoff = available.index[-1]
        if hasattr(history.data_pool, "get_all_bars"):
            available = history.data_pool.get_all_bars(self.symbol, copy=False)
            available = available.loc[:cutoff]
        daily_events = self.params.get("_daily_event_source", False)
        for stream in self._streams + [self._clock]:
            duration = stream["duration"]
            source = available
            if daily_events and "is_daily_close" in source:
                source = source[source.is_daily_close]
            if source.empty:
                continue
            keys = (source.tradingday.dt.normalize() if duration == 86400 else
                    source.index.floor(f"{duration}s"))
            grouped = source.groupby(np.asarray(keys), sort=True).agg(
                open=("open", "first"), high=("high", "max"), low=("low", "min"),
                close=("close", "last"), volume=("volume", "sum"), oi=("oi", "last"))
            grouped["timestamp"] = grouped.index
            rows = grouped.tail(stream.get("length", 1)+1).to_dict("records")
            stream["key"] = rows[-1]["timestamp"]
            if daily_events:
                stream["bucket"] = None
                closed = rows
            else:
                stream["bucket"] = rows[-1]
                closed = rows[:-1]
            if "history" in stream and closed:
                stream["history"].extend(closed[:-1])
                self._update_frame(stream, closed[-1])
        self._trading_day = pd.Timestamp(available.tradingday.iloc[-1]).normalize()
        day = available[available.tradingday == self._trading_day]
        self._day_open = float(day.open.iloc[0])

    @staticmethod
    def _key(bar, duration):
        if duration == 86400:
            return pd.Timestamp(bar.tradingday).normalize()
        stamp = pd.Timestamp(bar.timestamp)
        return pd.Timestamp(stamp.value // (duration*1_000_000_000) * duration*1_000_000_000)

    def _advance(self, stream, bar):
        key = self._key(bar, stream["duration"])
        completed = None
        if key != stream["key"] or stream["bucket"] is None:
            completed = stream["bucket"]
            stream["key"] = key
            stream["bucket"] = dict(timestamp=key, open=float(bar.open), high=float(bar.high),
                                    low=float(bar.low), close=float(bar.close),
                                    volume=float(bar.volume), oi=float(bar.oi), day_open=self._day_open,
                                    last_timestamp=pd.Timestamp(bar.timestamp))
        else:
            bucket = stream["bucket"]
            # A daily event source supplies the full day's OHLCV after its
            # execution row; its values must replace that partial row.
            stamp = pd.Timestamp(bar.timestamp)
            if stream["duration"] == 86400 and bar.is_daily_close:
                bucket.update(open=float(bar.open), high=float(bar.high), low=float(bar.low),
                              close=float(bar.close), volume=float(bar.volume), oi=float(bar.oi))
            else:
                bucket["high"] = max(bucket["high"], float(bar.high))
                bucket["low"] = min(bucket["low"], float(bar.low))
                bucket["close"] = float(bar.close)
                bucket["volume"] += float(bar.volume)
                bucket["oi"] = float(bar.oi)
            bucket["last_timestamp"] = pd.Timestamp(bar.timestamp)
        return completed

    @staticmethod
    def _update_frame(stream, completed):
        stream["history"].append(completed)
        rows = list(stream["history"])
        count = stream["length"] - int(stream["previous"])
        if len(rows) < count:
            return False
        rows = rows[-count:]
        if stream["previous"]:
            last = rows[-1]
            rows = rows + [dict(last, open=last["close"], high=last["close"],
                                low=last["close"], volume=0)]
        values = np.array([[pd.Timestamp(row["timestamp"]).value, i,
                            row["open"], row["high"], row["low"], row["close"],
                            row["volume"], row["oi"], row["oi"]]
                           for i, row in enumerate(rows)], dtype=float)
        frame = stream["frame"]
        if len(frame) == 0:
            for col, data in zip(frame.columns, values.T):
                frame[col] = data
        else:
            frame.iloc[:] = values
        # Stable monotonically advancing source IDs are essential to OBV/ADX.
        frame.loc[:, "id"] = np.arange(len(frame)) + completed["timestamp"].value // 1_000_000_000
        return True

    def _decision(self, completed):
        api = self._api
        api.sync_position(self.position.net_volume)
        api.target = None
        price = completed["close"]
        api.quote.last_price = api.quote.bid_price1 = api.quote.ask_price1 = price
        api.quote.open = completed.get("day_open", self._day_open)
        api.quote.datetime = str(completed.get("last_timestamp", completed["timestamp"]))
        next(self._program)
        target = api.target
        if target is None:
            locals_ = self._program.gi_frame.f_locals
            paper = locals_.get("position")
            if isinstance(paper, Real):
                target = int(paper)
            elif hasattr(locals_.get("strategy"), "position"):
                target = int(locals_["strategy"].position)
            elif api.desired_target is not None:
                target = api.desired_target
        if target is None:
            return None
        return (target > 0) - (target < 0) if self.source_name != "12_grid_trading" else target

    def on_bar(self, bar, snapshot):
        day = pd.Timestamp(bar.tradingday).normalize()
        if day != self._trading_day:
            self._trading_day, self._day_open = day, float(bar.open)
        any_completed = False
        latest = None
        self._api.changed.clear()
        self._api.changed_stamps.clear()
        stamp = pd.Timestamp(bar.timestamp)
        full_daily_event = self.params.get("_daily_event_source", False) and bar.is_daily_close
        for stream in self._streams:
            completed = self._advance(stream, bar)
            seconds = stream["duration"]
            intraday_end = (seconds < 86400 and (stamp.value // 1_000_000_000 + 60) % seconds == 0)
            if (full_daily_event and seconds == 86400) or intraday_end:
                completed = stream["bucket"]
                stream["bucket"] = None
            if completed is not None:
                any_completed = True
                latest = completed
                if self._update_frame(stream, completed):
                    self._api.changed.add(id(stream["frame"]))
                    self._api.changed_stamps.add(stream["frame"].iloc[-1]["datetime"])
        if self.source_name == "04_dual_thrust":
            quote_completed = self._advance(self._clock, bar)
            seconds = self._clock["duration"]
            if seconds < 86400 and (stamp.value // 1_000_000_000 + 60) % seconds == 0:
                quote_completed = self._clock["bucket"]
                self._clock["bucket"] = None
            latest = quote_completed
            any_completed = quote_completed is not None
        if not any_completed or not all(len(s["frame"]) for s in self._streams):
            return []
        target = self._decision(latest)
        if self.source_name == "12_grid_trading":
            from ._source_special import GridTradingStrategy
            return GridTradingStrategy._signals(self, bar, target)
        return self._signals(bar, target)
