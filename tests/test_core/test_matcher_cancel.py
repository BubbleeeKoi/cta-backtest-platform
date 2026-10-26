"""Matcher 的新能力测试：撤单 / 重复 cid 校验 / price-time 优先撮合。

对应升级方案 5.3 节。
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.matcher import Matcher
from framework.types import (
    FILL_CANCELLED,
    FILL_FILLED,
    OFFSET_OPEN,
    ORDER_LIMIT,
    Bar,
    Order,
)


def _bar(symbol, ts, o, h, l, c, v=100):
    return Bar(
        symbol=symbol, timestamp=pd.Timestamp(ts),
        tradingday=pd.Timestamp(ts).normalize(),
        open=o, high=h, low=l, close=c, volume=v,
    )


def _order(*, order_id, cid, direction, price, vol=1, otype=ORDER_LIMIT, ts="2024-01-01 09:00"):
    return Order(
        order_id=order_id, signal_id="s_" + order_id, strategy_id="t",
        symbol="RB", contract="RB",
        direction=direction, offset=OFFSET_OPEN,
        order_type=otype, volume=vol, price=price,
        submit_datetime=pd.Timestamp(ts),
        session="早盘盘中", tag="test",
        client_order_id=cid,
    )


CI = {"RB": {"point": 10, "tick_size": 1.0, "slip": 1.5}}


# ── 1. 单挂单撤单成功 ──────────────────────────────────────────────────

def test_cancel_existing_pending_returns_cancelled_fill():
    m = Matcher(CI)
    m.submit_pending(
        [_order(order_id="o1", cid="OPEN1", direction=1, price=3500)],
        pd.Timestamp("2024-01-01 09:00"),
    )
    fill = m.cancel("RB", "OPEN1")
    assert fill is not None
    assert fill.status == FILL_CANCELLED
    assert fill.fill_volume == 0
    assert fill.fill_price is None
    assert fill.client_order_id == "OPEN1"
    assert fill.order_id == "o1"
    # pending 列表应已清空
    assert m._pending.get("RB") in (None, [])


# ── 2. 撤一个不存在的 cid 静默返回 None ────────────────────────────────

def test_cancel_nonexistent_returns_none():
    m = Matcher(CI)
    m.submit_pending(
        [_order(order_id="o1", cid="OPEN1", direction=1, price=3500)],
        pd.Timestamp("2024-01-01 09:00"),
    )
    assert m.cancel("RB", "NOPE") is None
    assert m.cancel("XX", "OPEN1") is None
    # 原挂单仍在
    assert len(m._pending["RB"]) == 1


# ── 3. 同方向 3 笔限价开仓单按价格优先成交 ──────────────────────────────

def test_limit_buys_filled_by_price_time_priority():
    """三笔买单价格 3500 / 3600 / 3700，bar 覆盖三档，应按价高先成交。"""
    m = Matcher(CI)
    ts0 = pd.Timestamp("2024-01-01 09:00")
    m.submit_pending([
        _order(order_id="oA", cid="A", direction=1, price=3500, ts="2024-01-01 09:00"),
        _order(order_id="oB", cid="B", direction=1, price=3700, ts="2024-01-01 09:00"),
        _order(order_id="oC", cid="C", direction=1, price=3600, ts="2024-01-01 09:00"),
    ], ts0)

    # bar 区间 [3400, 3800]，三档全部触达
    bar = _bar("RB", "2024-01-01 09:01", o=3800, h=3800, l=3400, c=3500)
    fills = m.match_at(bar)
    cids_in_fill_order = [f.client_order_id for f in fills if f.status == FILL_FILLED]
    # 期望按价格高 → 低 顺序成交
    assert cids_in_fill_order == ["B", "C", "A"], (
        f"实际成交顺序 {cids_in_fill_order}"
    )


def test_same_price_buys_filled_by_submit_time():
    """同价多笔，按 submit_ts 早的先成交。"""
    m = Matcher(CI)
    m.submit_pending(
        [_order(order_id="o_early", cid="EARLY", direction=1, price=3500)],
        pd.Timestamp("2024-01-01 09:00"),
    )
    m.submit_pending(
        [_order(order_id="o_late", cid="LATE", direction=1, price=3500, ts="2024-01-01 09:00:30")],
        pd.Timestamp("2024-01-01 09:00:30"),
    )
    bar = _bar("RB", "2024-01-01 09:01", o=3500, h=3800, l=3400, c=3500)
    fills = m.match_at(bar)
    cids = [f.client_order_id for f in fills if f.status == FILL_FILLED]
    assert cids == ["EARLY", "LATE"]


def test_limit_sells_filled_by_price_priority():
    """卖单：价格低的先成交。"""
    m = Matcher(CI)
    ts0 = pd.Timestamp("2024-01-01 09:00")
    m.submit_pending([
        _order(order_id="oA", cid="A", direction=-1, price=3700),
        _order(order_id="oB", cid="B", direction=-1, price=3500),
        _order(order_id="oC", cid="C", direction=-1, price=3600),
    ], ts0)
    # bar 区间 [3400, 3800] 全部触达
    bar = _bar("RB", "2024-01-01 09:01", o=3500, h=3800, l=3400, c=3500)
    fills = m.match_at(bar)
    cids = [f.client_order_id for f in fills if f.status == FILL_FILLED]
    # 期望按价格低 → 高 顺序成交
    assert cids == ["B", "C", "A"], f"实际成交顺序 {cids}"


# ── 4. 同 symbol 重复 client_order_id → raise ValueError ───────────────

def test_duplicate_cid_against_pending_raises():
    m = Matcher(CI)
    m.submit_pending(
        [_order(order_id="o1", cid="DUP", direction=1, price=3500)],
        pd.Timestamp("2024-01-01 09:00"),
    )
    with pytest.raises(ValueError, match="重复 client_order_id"):
        m.submit_pending(
            [_order(order_id="o2", cid="DUP", direction=1, price=3600)],
            pd.Timestamp("2024-01-01 09:01"),
        )


def test_duplicate_cid_within_batch_raises():
    m = Matcher(CI)
    with pytest.raises(ValueError, match="同一批 Signal 内"):
        m.submit_pending([
            _order(order_id="o1", cid="DUP", direction=1, price=3500),
            _order(order_id="o2", cid="DUP", direction=1, price=3600),
        ], pd.Timestamp("2024-01-01 09:00"))


def test_no_cid_does_not_trigger_uniqueness_check():
    """client_order_id 为 None 时不参与唯一性校验（向后兼容老策略）。"""
    m = Matcher(CI)
    m.submit_pending([
        _order(order_id="o1", cid=None, direction=1, price=3500),
        _order(order_id="o2", cid=None, direction=1, price=3600),
    ], pd.Timestamp("2024-01-01 09:00"))
    assert len(m._pending["RB"]) == 2


# ── 5. client_order_id 在所有 fill 路径上透传 ─────────────────────────

def test_client_order_id_propagates_to_filled():
    m = Matcher(CI)
    m.submit_pending(
        [_order(order_id="o1", cid="TPL1", direction=1, price=3500)],
        pd.Timestamp("2024-01-01 09:00"),
    )
    bar = _bar("RB", "2024-01-01 09:01", o=3500, h=3600, l=3400, c=3500)
    fills = m.match_at(bar)
    assert fills[0].client_order_id == "TPL1"
