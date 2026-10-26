"""Explicit account-capital ratios and marked-price margin estimates."""
from __future__ import annotations
import numpy as np
import pandas as pd


def account_metrics(curve, start=None, end=None):
    frame = curve.sort_values("date")
    initial = float(frame.initial_capital.iloc[0])
    if initial <= 0:
        raise ValueError("Initial capital must be positive")
    values = frame.equity.astype(float).to_numpy()
    peaks = np.maximum.accumulate(np.r_[initial, values])[1:]
    drops = peaks-values
    total = float(values[-1]-initial)
    first = pd.Timestamp(start or frame.date.iloc[0]).normalize()
    last = pd.Timestamp(end or frame.date.iloc[-1]).normalize()
    days = max(1, (last-first).days+1)
    annual = total*365/days
    initial_loss = max(0., initial-float(values.min()))
    return dict(initial_capital=initial, final_equity=float(values[-1]), total_pnl=total,
                total_return_pct=total/initial*100, profit_multiple=total/initial,
                final_equity_multiple=float(values[-1])/initial,
                max_drawdown_amount=float(drops.max()),
                max_drawdown_initial_pct=float(drops.max())/initial*100,
                max_drawdown_initial_multiple=float(drops.max())/initial,
                max_initial_loss_amount=initial_loss, max_initial_loss_pct=initial_loss/initial*100,
                max_drawdown_pct=-float(np.max(drops/peaks))*100,
                simple_annual_pnl=annual, simple_annual_return_pct=annual/initial*100,
                simple_annual_profit_multiple=annual/initial, period_calendar_days=days)


def margin_metrics(actions, bars, initial, point, rate, strategies, start=None, end=None):
    unavailable = dict(margin_available=False, margin_note="缺少完整成交事件或保证金参数，无法估算占用")
    if bars is None or bars.empty or actions is None or len(actions) == 0:
        return unavailable
    if not np.isfinite(point) or not np.isfinite(rate) or point <= 0 or not 0 < rate <= 1:
        return unavailable
    fills = pd.DataFrame(actions)
    required = {"event", "ts", "fill_volume", "fill_price", "direction", "offset", "strategy_id"}
    if not required <= set(fills.columns):
        return unavailable
    fills = fills[fills.event.isin(["fill_filled", "fill_partial"])
                  & fills.strategy_id.astype(str).isin(strategies)].copy()
    fills["ts"] = pd.to_datetime(fills.ts)
    fills["fill_volume"] = pd.to_numeric(fills.fill_volume, errors="coerce").fillna(0)
    fills = fills[fills.fill_volume > 0].sort_values("ts", kind="stable")
    market = bars.sort_index()
    if start is not None:
        market = market[market.index >= pd.Timestamp(start)]
    if end is not None:
        market = market[market.index <= pd.Timestamp(end)]
    if market.empty:
        return unavailable
    # Include actual fill prices as well as observed minute highs; high-marked
    # margin is conservative within each bar, and is not exchange settlement margin.
    index = market.index.union(pd.DatetimeIndex(fills.ts)).sort_values()
    high = market.high.astype(float).reindex(index).ffill()
    fill_price = fills.groupby("ts").fill_price.max().reindex(index)
    marks = pd.concat([high, fill_price], axis=1).max(axis=1)
    total_lots = pd.Series(0., index=index)
    for _, group in fills.groupby("strategy_id"):
        opened = group.offset.eq("open")
        long_delta = np.where(opened & group.direction.eq(1), group.fill_volume,
                              np.where(~opened & group.direction.eq(-1), -group.fill_volume, 0))
        short_delta = np.where(opened & group.direction.eq(-1), group.fill_volume,
                               np.where(~opened & group.direction.eq(1), -group.fill_volume, 0))
        deltas = pd.DataFrame(dict(long=long_delta, short=short_delta), index=group.ts)
        positions = deltas.groupby(level=0).sum().cumsum()
        if (positions < -1e-8).any().any():
            return dict(unavailable, margin_note="成交事件不完整，存在无对应开仓的平仓")
        total_lots += positions.sum(axis=1).reindex(index, method="ffill").fillna(0)
    notionals = total_lots*marks*point
    margins = notionals*rate
    maximum = float(margins.max())
    return dict(margin_available=True, margin_rate=rate, max_margin_amount=maximum,
                max_margin_initial_pct=maximum/initial*100,
                max_margin_initial_multiple=maximum/initial,
                max_notional_amount=float(notionals.max()),
                max_margin_time=str(margins.idxmax()) if maximum else None,
                margin_note="按成交重建持仓、分钟最高价和元数据固定保证金率估算；非历史结算保证金")
