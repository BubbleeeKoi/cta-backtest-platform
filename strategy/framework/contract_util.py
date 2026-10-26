"""
framework/contract_util.py  ——  合约元信息工具

策略与执行层共用的合约相关计算（不依赖任何特定策略状态）：
    normalize_symbol            从任意 raw 值规整出大写品种代码
    infer_symbol_from_contract_info  从 dict / object 推断品种代码
    clip01                      数值裁剪到 [0, 1]
    tick_size                   合约最小变动价位
    commission_per_side         单边手续费（按固定或费率自适配）
    roundtrip_cost_price        双边手续费换算成"价格差"维度
    notional_volume             名义资金 → 手数（策略层产 Signal.volume_hint 用）
"""
from __future__ import annotations

import re


def normalize_symbol(raw: object) -> str:
    """从任意 raw 值规整出大写品种代码（去掉交易所后缀、保留字母前缀）。"""
    if raw in (None, ""):
        return ""
    s = str(raw).split(".")[0].strip().upper()
    m = re.match(r"^[A-Z]+", s)
    return m.group(0) if m else s


_SYMBOL_PRIORITY_KEYS = ("product", "symbol", "name", "ts_code")


def infer_symbol_from_contract_info(contract_info) -> str:
    """从 dict 或 object 中推断品种代码（大写、剥离交易所后缀）。

    优先级（与 ``BacktestDataPool.contract_info`` 实际填充顺序一致）：
        product > symbol > name > ts_code

    支持的输入形态：
        - dict（如 ``BacktestDataPool.contract_info(sym)`` 的返回）
        - pd.Series（future_list.loc[sym]；index label 在 ``.name``）
        - 任意持有上述属性的对象

    解析失败返回空字符串 ``""``；外层若需要 None 语义可自行转换。
    """
    if contract_info is None:
        return ""
    is_dict = isinstance(contract_info, dict)
    for key in _SYMBOL_PRIORITY_KEYS:
        raw = contract_info.get(key) if is_dict else getattr(contract_info, key, None)
        sym = normalize_symbol(raw)
        if sym:
            return sym
    return ""


def clip01(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


def tick_size(contract_info) -> float:
    """读取合约 tick 大小；缺失时返回 1.0。"""
    raw = contract_info.get(
        "tick", contract_info.get("min_tick", contract_info.get("tick_size", 1.0))
    )
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 1.0


def commission_per_side(contract_info, entry_price: float) -> float:
    """单边手续费：``type=0`` 视为定额，``type=1`` 视为费率，否则按 rate>=1 自适配。"""
    raw = contract_info.get("commission_intraday")
    if raw in (None, ""):
        raw = contract_info.get("commission")
    if raw in (None, ""):
        return 5.0
    try:
        rate = float(raw)
    except (TypeError, ValueError):
        return 5.0
    raw_type = contract_info.get("type")
    try:
        t = float(raw_type)
        if t == 0.0:
            return rate
        if t == 1.0:
            return rate * entry_price * float(contract_info.get("point", 10.0))
    except (TypeError, ValueError):
        pass
    if rate >= 1.0:
        return rate
    return rate * entry_price * float(contract_info.get("point", 10.0))


def roundtrip_cost_price(contract_info, entry_price: float) -> float:
    """双边手续费按价格差维度返回：``2 * commission_per_side / point``。"""
    point = float(contract_info.get("point", 10.0))
    if point == 0.0:
        return 0.0
    comm_entry_side = float(commission_per_side(contract_info, float(entry_price)))
    return (2.0 * comm_entry_side) / point


def notional_volume(allocated_capital: float, price: float, point: float) -> int:
    """名义资金 → 手数：``max(1, round(allocated_capital / (price * point)))``。

    各成员策略在 ``on_bar`` / ``precompute.build_batch_signals`` 中以 ORDER_EXACT
    挂单时，统一用本函数填充 ``Signal.volume_hint``，与 ``core.sizing.NotionalSizer``
    在 ORDER_MARKET 路径上的 ``calc_volume(price, point)`` 在正常输入下数值一致。

    边界语义：
        - ``price <= 0`` 或 ``point <= 0`` 时返回 ``0``，意味本笔信号不下单
          （上层 framework 在 ``volume_hint=0`` 时会跳过订单生成）。
          这与 ``NotionalSizer.calc_volume`` 的"返回 1"防御性语义略有差异：
          后者用于已经确认要下单的 ORDER_MARKET 路径，此处用于策略侧"是否
          应该下单"的决策路径。
    """
    if price <= 0 or point <= 0:
        return 0
    vol = allocated_capital / (price * point)
    return max(1, int(round(vol)))


__all__ = [
    "normalize_symbol",
    "infer_symbol_from_contract_info",
    "clip01",
    "tick_size",
    "commission_per_side",
    "roundtrip_cost_price",
    "notional_volume",
]
