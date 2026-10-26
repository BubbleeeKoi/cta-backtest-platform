"""测试 Strategy.new_client_order_id 的全局唯一性、长度、字符集。

覆盖文档第 5.2 节交易系统规则:
    - 全局唯一（含跨实例 / 多线程并发）
    - 长度 ≤ 21 字节
    - 仅 ASCII 字母 / 数字（全大写）
    - prefix 仅作可读性辅助
"""
from __future__ import annotations

import concurrent.futures
import re
import string

import pandas as pd

from framework.base import Strategy
from framework.data_pool import DataPool


# Strategy 的最小可实例化子类（不实现 on_bar 也可以构造对象）
class _DummyStrategy(Strategy):
    def on_bar(self, bar, snapshot):
        return []


class _NullDataPool(DataPool):
    """DataPool 是 ABC；本测试只需要构造实例传给 Strategy.__init__，不会被调用。"""
    def list_universe(self):
        return []

    def sector_of(self, symbol):
        return ""

    def symbols_in_sector(self, sector, exclude=None):
        return []

    def contract_info(self, symbol):
        return {}

    def get_minute_bars(self, symbol, as_of, n_bars):
        return pd.DataFrame()

    def get_session_bars(self, symbol, tradingday, session_start, session_end):
        return pd.DataFrame()

    def get_daily_panel(self, metric, symbols, as_of_td, n_days):
        return pd.DataFrame()


def _make_strategy(strategy_id: str = "t") -> _DummyStrategy:
    return _DummyStrategy(
        strategy_id=strategy_id,
        contract_info={"product": "RB", "point": 10, "tick_size": 1.0, "slip": 1.5},
        data_pool=_NullDataPool(),
        params={},
    )


_ALLOWED = set(string.digits + string.ascii_uppercase)


def test_client_order_id_format():
    s = _make_strategy()
    cid = s.new_client_order_id()
    assert len(cid) <= 21
    assert all(c in _ALLOWED for c in cid), f"非法字符: {cid!r}"
    assert re.fullmatch(r"[0-9A-Z]+", cid) is not None


def test_client_order_id_with_prefix_includes_prefix_uppercase():
    s = _make_strategy()
    cid = s.new_client_order_id("open")
    assert cid.startswith("OPEN")
    assert len(cid) <= 21
    assert all(c in _ALLOWED for c in cid)


def test_client_order_id_prefix_strips_non_alnum():
    s = _make_strategy()
    cid = s.new_client_order_id("op_long-1!")
    # 仅保留字母数字
    assert cid.startswith("OPLONG1")
    assert all(c in _ALLOWED for c in cid)


def test_client_order_id_unique_within_single_strategy():
    s = _make_strategy()
    ids = {s.new_client_order_id() for _ in range(2000)}
    assert len(ids) == 2000, "同实例内 2000 次调用必须全部不重复"


def test_client_order_id_unique_across_strategies():
    s1 = _make_strategy("alpha")
    s2 = _make_strategy("beta")
    ids = set()
    for _ in range(1000):
        ids.add(s1.new_client_order_id())
        ids.add(s2.new_client_order_id())
    assert len(ids) == 2000, "跨实例不应重复（共享类级计数器）"


def test_client_order_id_thread_safe():
    """16 线程 × 1000 次并发分配，应无重复。"""
    s = _make_strategy()
    ids = []
    lock = __import__("threading").Lock()

    def _worker():
        local = [s.new_client_order_id() for _ in range(1000)]
        with lock:
            ids.extend(local)

    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(lambda _: _worker(), range(16)))

    assert len(set(ids)) == len(ids), (
        f"多线程并发分配出现重复: 总 {len(ids)}，去重后 {len(set(ids))}"
    )


def test_client_order_id_prefix_does_not_overflow_length():
    s = _make_strategy()
    # 即使 prefix 很长，最终长度也 ≤ 21
    cid = s.new_client_order_id("X" * 50)
    assert len(cid) <= 21
