"""
framework/signal_recorder.py  ——  策略信号落盘（回测 / 实盘共用）

用途
    实盘运行后，把当日每条 Signal 落到 CSV；同样的策略代码用同源行情
    重跑一遍回测，得到"应当发出"的 signals.csv，两份做 diff 即可
    验证实盘是否按既定策略发出了信号。

为什么不在策略层做
    Signal 是策略对外的纯净输出，由引擎在 ``tag_signal`` 之后统一漏斗。
    在引擎层落盘可保证:
      1. 所有运行路径都覆盖到（单品种快路径 / 多品种 / 批量稀疏路径）
      2. 策略包零修改即可享受对账能力

落盘 schema（CSV，columns 固定，跨数据源稳定）
    strategy_id, symbol, tradingday,
    action_datetime, bar_datetime,
    signal_kind, direction, offset, order_type,
    price, volume_hint, session, tag, signal_id,
    bar_open, bar_high, bar_low, bar_close, bar_volume, bar_oi

匹配键（建议）::
    (strategy_id, symbol, action_datetime, bar_datetime,
     signal_kind, direction, offset)

  非匹配键：
    - signal_id : uuid，每次跑都不同；只用于排查
    - bar_*     : 行情上下文，mismatch 时辅助定位是不是数据源差异

线程安全
    本类**非线程安全**。引擎主循环是单线程，无需加锁；如未来引入并发
    采集需要由调用方自行加锁。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd

from .types import Bar, Signal

_COLUMNS: tuple[str, ...] = (
    "strategy_id", "symbol", "tradingday",
    "action_datetime", "bar_datetime",
    "signal_kind", "direction", "offset", "order_type",
    "price", "volume_hint", "session", "tag", "signal_id",
    "bar_open", "bar_high", "bar_low", "bar_close", "bar_volume", "bar_oi",
)


@dataclass
class _Row:
    """避免每次 record 都构造 dict；落盘时统一组装。"""
    strategy_id: str
    symbol: str
    tradingday: Optional[pd.Timestamp]
    action_datetime: pd.Timestamp
    bar_datetime: pd.Timestamp
    signal_kind: str
    direction: int
    offset: str
    order_type: str
    price: Optional[float]
    volume_hint: Optional[int]
    session: str
    tag: str
    signal_id: str
    bar_open: Optional[float]
    bar_high: Optional[float]
    bar_low: Optional[float]
    bar_close: Optional[float]
    bar_volume: Optional[float]
    bar_oi: Optional[float]


class SignalRecorder:
    """记录策略发出的 Signal，可落盘成 CSV。

    用法（回测端）:
        recorder = SignalRecorder()
        engine = BacktestEngine(..., signal_recorder=recorder)
        engine.run()
        recorder.save(Path("output/signals/signals_run.csv"))

    用法（实盘端，IT 接入时）:
        recorder = SignalRecorder()
        # 每根 bar 收到策略返回的 signals 后:
        for sig in signals:
            recorder.record(sig, current_bar)
        # 日终:
        recorder.save(Path(f"live_output/signals/signals_{date}.csv"))
    """

    def __init__(self) -> None:
        self._rows: List[_Row] = []

    # ── 采集 ─────────────────────────────────────────────────────────

    def record(self, signal: Signal, bar: Optional[Bar] = None) -> None:
        """记录一条 signal；bar 是触发它的 K 线（缺省时仍可记录，但失去对账上下文）。"""
        if bar is not None and bar.symbol != signal.symbol:
            # 跨品种 bar：通常不应出现；保守记录但标记 bar_* 为 None
            bar = None
        self._rows.append(_Row(
            strategy_id     = signal.strategy_id,
            symbol          = signal.symbol,
            tradingday      = bar.tradingday if bar is not None else None,
            action_datetime = signal.action_datetime,
            bar_datetime    = signal.bar_datetime,
            signal_kind     = signal.signal_kind,
            direction       = int(signal.direction),
            offset          = signal.offset,
            order_type      = signal.order_type,
            price           = signal.price,
            volume_hint     = signal.volume_hint,
            session         = signal.session,
            tag             = signal.tag,
            signal_id       = signal.signal_id,
            bar_open   = bar.open   if bar is not None else None,
            bar_high   = bar.high   if bar is not None else None,
            bar_low    = bar.low    if bar is not None else None,
            bar_close  = bar.close  if bar is not None else None,
            bar_volume = bar.volume if bar is not None else None,
            bar_oi     = bar.oi     if bar is not None else None,
        ))

    # ── 输出 ─────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        if not self._rows:
            return pd.DataFrame(columns=list(_COLUMNS))
        rows = [
            {
                "strategy_id":      r.strategy_id,
                "symbol":           r.symbol,
                "tradingday":       r.tradingday,
                "action_datetime":  r.action_datetime,
                "bar_datetime":     r.bar_datetime,
                "signal_kind":      r.signal_kind,
                "direction":        r.direction,
                "offset":           r.offset,
                "order_type":       r.order_type,
                "price":            r.price,
                "volume_hint":      r.volume_hint,
                "session":          r.session,
                "tag":              r.tag,
                "signal_id":        r.signal_id,
                "bar_open":         r.bar_open,
                "bar_high":         r.bar_high,
                "bar_low":          r.bar_low,
                "bar_close":        r.bar_close,
                "bar_volume":       r.bar_volume,
                "bar_oi":           r.bar_oi,
            }
            for r in self._rows
        ]
        df = pd.DataFrame(rows, columns=list(_COLUMNS))
        # 排序：按 (strategy, symbol, action_datetime) 稳定排序，便于直观浏览/diff
        return df.sort_values(
            ["strategy_id", "symbol", "action_datetime"], kind="mergesort"
        ).reset_index(drop=True)

    def save(self, path: Path | str) -> Path:
        """落盘 CSV；自动建目录。返回最终 Path。"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        df = self.to_dataframe()
        df.to_csv(p, index=False, encoding="utf-8-sig")
        return p

    def __len__(self) -> int:
        return len(self._rows)

    def clear(self) -> None:
        self._rows.clear()
