"""
framework/base.py  ——  Strategy 基类

所有团队成员策略继承本类。回测与实盘两端**部署同一份代码**。

子类必须实现:
    on_bar(bar, snapshot) -> List[Signal]

子类可选实现:
    on_init(history)            预热钩子（回测启动前；实盘启动时）
    on_fill(fill)               成交回报；调 super() 自动维护 self.position
    on_day_end(td)              日终钩子（用于无 bar 触发的尾盘强平）

子类可选声明类属性:
    SESSION_NAMES               List[str]  参与 NAV 分组的时段名
    SUPPORTS_BATCH_PREBUILD     bool       是否支持批量预算快路径

批量预算契约（仅 SUPPORTS_BATCH_PREBUILD=True 的策略需实现）:
    batch_prebuild_args(self) -> Optional[dict]
    run_batch_prebuild(cls, args) -> Optional[Dict[Timestamp, List[Signal]]]
    get_prebuilt_signals(self) -> Optional[Dict[Timestamp, List[Signal]]]
    set_prebuilt_signals(self, signals) -> None
"""
from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

from .contract_util import infer_symbol_from_contract_info
from .data_pool import DataPool
from .snapshot import HistoryView, Snapshot
from .types import Bar, Fill, Position, Signal


# base36 字符集；用于 _b36 编码，限定 client_order_id 字符集为 [0-9A-Z]
_B36_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _b36(n: int) -> str:
    """非负整数 → base36 字符串（仅 0-9 A-Z）。0 返回 "0"。"""
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, 36)
        out.append(_B36_DIGITS[r])
    return "".join(reversed(out))


class Strategy:
    """
    CTA 策略基类。

    实例化方式（由框架调用，成员策略不要自己 new）:
        strategy = SubStrategy(
            strategy_id   = "jerome",
            contract_info = {...},   # future_list.csv 一行
            data_pool     = data_pool,
            params        = {...},   # 来自 strategies/<name>/config.yaml
        )
        strategy.on_init(history)
        for bar in stream:
            signals = strategy.on_bar(bar, snapshot)
            ...
            strategy.on_fill(fill)
    """

    # ──────────────────────────────────────────────────────────────────
    # 子类可选覆盖的类属性
    # ──────────────────────────────────────────────────────────────────

    # 参与 NAV 分组的时段名（由策略包自行定义，与本策略发出的 Signal.session 一一对应）
    SESSION_NAMES: List[str] = []

    # 是否支持「批量预算 + 稀疏成交」快路径。
    #   False（默认）：引擎按 on_bar 全量推进；适合实盘 / 简单逐 bar 决策的策略。
    #   True：实现 batch_prebuild_args / run_batch_prebuild / get_prebuilt_signals
    #         / set_prebuilt_signals 四个 hook；引擎在预热阶段并行预算，
    #         主循环只访问"信号 + 成交"两类时刻。
    #   注意：使用 cancel_order 的策略必须设为 False，确保回测/实盘行为一致
    #   （稀疏路径不调 on_bar，无法支持运行时撤单语义）。
    SUPPORTS_BATCH_PREBUILD: bool = False

    # ──────────────────────────────────────────────────────────────────
    # client_order_id 生成：类级（进程内）自增计数器
    #   - 同一进程内所有策略实例共享；线程安全
    #   - multiprocessing spawn 子进程会重置为 0；不影响全局唯一性，
    #     因为 ID 还混入了 pid 后 4 位 + 时间纳秒后 5 位作为跨进程区分度
    # ──────────────────────────────────────────────────────────────────
    _cid_global_lock = threading.Lock()
    _cid_global_counter = 0

    # ──────────────────────────────────────────────────────────────────
    # 框架调用入口
    # ──────────────────────────────────────────────────────────────────

    def __init__(
        self,
        strategy_id: str,
        contract_info: dict,
        data_pool: DataPool,
        params: dict | None = None,
    ) -> None:
        self.strategy_id = strategy_id
        # contract_info 统一规整为 dict；接受 pd.Series / dict 两种入参形态。
        # 同时保留品种代码到 dict["product"] 以便下游消费方稳定取用。
        symbol = infer_symbol_from_contract_info(contract_info) or "UNKNOWN"
        if hasattr(contract_info, "to_dict"):
            ci_dict: dict = contract_info.to_dict()  # type: ignore[union-attr]
        else:
            ci_dict = dict(contract_info)
        ci_dict.setdefault("product", symbol)
        self.contract_info = ci_dict
        self.data_pool = data_pool
        self.params = params or {}

        # 当前品种代码（与 strategy_id 不同，strategy_id 指策略名）
        self.symbol: str = symbol

        # 自动维护持仓
        self.position = Position(symbol=self.symbol)

        # 本 bar 内策略累积的撤单请求；引擎在 _step_bar 内 _drain_cancels() 取走
        # 格式：[(symbol, client_order_id), ...]
        self._pending_cancels: List[Tuple[str, str]] = []

    # ── 必须实现 ──────────────────────────────────────────────────────

    def on_bar(self, bar: Bar, snapshot: Snapshot) -> List[Signal]:
        """
        每根 bar 调用一次，返回该 bar 触发的 Signal 列表。

        **严禁穿越未来**：只能用 bar.timestamp 之前（含）的数据。
        """
        raise NotImplementedError(f"{type(self).__name__} 必须实现 on_bar()")

    # ── 可选钩子 ──────────────────────────────────────────────────────

    def on_init(self, history: HistoryView) -> None:
        """
        启动一次性预热。

        回测：传入测试窗口之前的历史 bar（warmup 段）
        实盘：传入最近 N 日历史 bar（来自行情服务）

        默认空实现；需要预计算因子的策略覆盖之。
        """
        pass

    def on_fill(self, fill: Fill) -> None:
        """
        成交回报。

        默认行为：自动把 fill 累计进 self.position。
        子类如需做拒单后补单等额外逻辑，**务必调用 super().on_fill(fill)**
        以保持 position 同步。
        """
        self.position.apply_fill(fill)

    def on_day_end(self, td: pd.Timestamp) -> List[Signal]:
        """
        日终钩子：用于无 bar 触发的尾盘强平等场景。可选。

        默认空实现，返回 []。
        """
        return []

    # ──────────────────────────────────────────────────────────────────
    # 挂单 / 撤单 API
    # ──────────────────────────────────────────────────────────────────

    def new_client_order_id(self, prefix: str = "") -> str:
        """
        生成框架保证全局唯一的 client_order_id。

        交易系统规则（兼容 CTP OrderRef）:
            - 全局唯一（含跨策略 / 跨进程的回测 / 实盘场景）
            - 长度 ≤ 21 字节
            - 仅 ASCII 字母 / 数字（不含下划线、特殊字符或中文）
            - 全大写

        格式（回测默认实现）:
            base36(进程pid 后 4 位) + base36(全局自增计数器)
                + base36(time.time_ns() 后 5 位)
            例: "F1Q2R3S4T"        （约 9~12 字节）

        prefix 参数:
            可读性辅助。如果传了 prefix，会以 ``{PREFIX_UPPER}{base}`` 拼出，
            并截断到 21 字节；仅做调试 / 日志用，不影响唯一性。
            例: new_client_order_id("open") → "OPENF1Q2R3S4T"
            建议 prefix ≤ 8 字符，且仅 ASCII 字母 / 数字。

        实盘部署时:
            实盘端可以重写本方法，改用经纪商分配的 OrderRef 池或
            ``trading_day + 自增序号``。接口签名保持一致即可。
        """
        with Strategy._cid_global_lock:
            Strategy._cid_global_counter += 1
            seq = Strategy._cid_global_counter
        # base36 编码 → 仅含 [0-9A-Z]，紧凑且符合交易所字符集
        body = (
            _b36(os.getpid() & 0xFFFF)
            + _b36(seq)
            + _b36(time.time_ns() & 0xFFFFF)
        )
        body = body[:21]
        if prefix:
            head = "".join(c for c in prefix.upper() if c.isalnum())[:8]
            body = (head + body)[:21]
        return body

    def cancel_order(self, symbol: str, client_order_id: str) -> None:
        """
        请求撤掉该 symbol 下指定 client_order_id 的挂单。

        - 仅在 on_bar / on_day_end 内调用有意义；引擎在收完信号后统一处理。
        - 撤单成功会以 ``FILL_CANCELLED`` 状态触发一次 ``on_fill``。
        - 若该 client_order_id 已成交 / 已过期 / 不存在，本次撤单静默忽略。
        - 同一 bar 内可调用多次撤多笔。
        - 不能在 ``SUPPORTS_BATCH_PREBUILD = True`` 的策略里使用；引擎在稀疏
          路径运行时会断言 ``_pending_cancels`` 必须为空。
        """
        self._pending_cancels.append((symbol, client_order_id))

    def _drain_cancels(self) -> List[Tuple[str, str]]:
        """框架内部使用：取出并清空本 bar 累积的撤单请求。"""
        cancels, self._pending_cancels = self._pending_cancels, []
        return cancels

    # ──────────────────────────────────────────────────────────────────
    # 批量预算契约（可选；SUPPORTS_BATCH_PREBUILD=True 的策略需覆盖）
    # ──────────────────────────────────────────────────────────────────

    def batch_prebuild_args(self) -> Optional[dict]:
        """返回可在 spawn 子进程序列化的预算参数字典；None 表示放弃并行预算。

        默认 None（不支持批量路径）。覆盖时必须返回 picklable dict，且必须
        包含足以让 ``run_batch_prebuild`` 重建策略状态的所有上下文（自身/peer
        DataFrame、StrategyParams、contract_info、allocated_capital 等）。
        """
        return None

    @classmethod
    def run_batch_prebuild(cls, args: dict) -> Optional[Dict[pd.Timestamp, List[Signal]]]:
        """子进程内调用：基于 args 重建状态、预算 ``{bar_timestamp: [Signal]}``。

        默认返回 None。覆盖此方法的策略必须保证子进程内可独立 import 并完成
        预算（不持有任何主进程对象引用）。
        """
        return None

    def get_prebuilt_signals(self) -> Optional[Dict[pd.Timestamp, List[Signal]]]:
        """返回已预算好的批量信号字典；未预算返回 None。

        引擎据此判定"是否走稀疏快路径"。默认 None。
        """
        return None

    def set_prebuilt_signals(self, signals: Dict[pd.Timestamp, List[Signal]]) -> None:
        """注入子进程预算好的信号字典。

        默认空实现（不支持批量路径的策略忽略）。
        """
        pass
