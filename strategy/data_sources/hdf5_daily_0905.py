"""Aggregate HDF5 minute data into daily bars and 09:05 execution events.

Only two events per trading day reach the backtest engine: the original 09:05
minute and an aggregated daily bar timestamped at its last minute. The
original ``tradingday`` field assigns night sessions to their exchange day.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from .base import MinuteBarSource, validate_schema


def _event_positions(timestamps: pd.DatetimeIndex,
                     tradingdays: pd.DatetimeIndex) -> np.ndarray:
    """Select 09:05 and completed-day close rows in chronological order."""
    frame = pd.DataFrame({
        "timestamp": timestamps,
        "tradingday": tradingdays,
        "row": np.arange(len(timestamps)),
    })
    if not frame["timestamp"].is_monotonic_increasing:
        frame = frame.sort_values("timestamp")

    # 09:05 belongs to the daytime portion of its own trading day.
    morning = frame[
        (frame["timestamp"].dt.hour == 9)
        & (frame["timestamp"].dt.minute == 5)
        & (frame["timestamp"].dt.second == 0)
        & (frame["timestamp"].dt.normalize() == frame["tradingday"])
    ].drop_duplicates("tradingday", keep="first")
    # Financial futures have no 09:05 candle. Use their first actual daytime
    # minute, without inventing an earlier timestamp or forward-looking price.
    missing_morning = frame[
        ~frame["tradingday"].isin(morning["tradingday"])
        & (frame["timestamp"].dt.normalize() == frame["tradingday"])
        & (frame["timestamp"].dt.hour >= 9)
    ].drop_duplicates("tradingday", keep="first")
    morning = pd.concat([morning, missing_morning])

    close = frame.groupby("tradingday", sort=False).tail(1)
    # An incomplete day consisting only of a night session, or ending at
    # 09:05, cannot supply a completed daily close.
    close = close[
        (close["timestamp"].dt.normalize() == close["tradingday"])
        & ((close["timestamp"].dt.hour > 9)
           | ((close["timestamp"].dt.hour == 9)
              & (close["timestamp"].dt.minute > 5)))
    ]
    return np.union1d(morning["row"].to_numpy(), close["row"].to_numpy())


class HDF5Daily0905Source(MinuteBarSource):
    """Aggregate one HDF5 symbol into daily decision and execution events."""

    def __init__(self, data_dir: str) -> None:
        self._data_dir = Path(data_dir)

    def load(self, symbol: str) -> pd.DataFrame | None:
        path = self._data_dir / f"{symbol}.h5"
        if not path.is_file():
            return None

        with h5py.File(path, "r") as h5:
            if symbol not in h5:
                return None
            group = h5[symbol]
            timestamps = pd.DatetimeIndex(pd.to_datetime(group["axis1"][:]))
            td_raw = pickle.loads(bytes(group["block2_values"][0])).flatten()
            td_values = [x[0] if isinstance(x, (list, np.ndarray)) else x
                         for x in td_raw]
            tradingdays = pd.DatetimeIndex(pd.to_datetime(td_values, format="%Y%m%d"))
            if len(timestamps) != len(tradingdays):
                raise ValueError(f"{symbol}: timestamps and tradingday lengths differ")
            rows = _event_positions(timestamps, tradingdays)
            if len(rows) == 0:
                return None

            b0_cols = [x.decode() for x in group["block0_items"][:]]
            b1_cols = [x.decode() for x in group["block1_items"][:]]
            frame = pd.DataFrame(
                group["block0_values"][rows, :],
                index=pd.DatetimeIndex(timestamps[rows], name="actiontime"),
                columns=b0_cols,
            )
            b1 = group["block1_values"][rows, :]
            for i, col in enumerate(b1_cols):
                frame[col] = b1[:, i]
            frame["tradingday"] = tradingdays[rows]
            frame["actionday"] = frame.index.normalize()

            # The daily event carries the complete trading day's OHLCV,
            # including the night session. Keep the 09:05 event untouched so
            # its open remains the exact execution reference price.
            final_rows = pd.DataFrame({"td": tradingdays, "row": np.arange(len(timestamps))}).groupby("td", sort=False).tail(1)["row"].to_numpy()
            close_event = np.isin(rows, final_rows)
            frame["is_daily_close"] = close_event
            if close_event.any():
                raw = pd.DataFrame(group["block0_values"][:], columns=b0_cols)
                raw["volume"] = group["block1_values"][:, b1_cols.index("volume")]
                raw["tradingday"] = tradingdays
                daily = raw.groupby("tradingday", sort=False).agg(
                    open=("open", "first"), high=("high", "max"),
                    low=("low", "min"), close=("close", "last"),
                    volume=("volume", "sum"),
                )
                daily_rows = daily.loc[tradingdays[rows[close_event]],
                                       ["open", "high", "low", "close", "volume"]]
                frame.loc[close_event, ["open", "high", "low", "close", "volume"]] = daily_rows.to_numpy()

        return validate_schema(frame, symbol, self.describe())

    def list_available_symbols(self) -> list[str]:
        if not self._data_dir.is_dir():
            return []
        return sorted(path.stem for path in self._data_dir.glob("*.h5"))

    def describe(self) -> str:
        return f"HDF5Daily0905Source({self._data_dir})"
