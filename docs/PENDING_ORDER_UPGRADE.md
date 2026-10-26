# 挂单 / 撤单能力升级方案

> **状态：设计已定稿，等待启动实施**
> **范围：`framework/types.py` · `framework/base.py` · `core/matcher.py` · `core/engine/loop.py` · `core/portfolio_adapter.py`**
>
> 最终决策汇总见文末第 11 节。

---

## 1. 背景与动机

当前框架基于 "Signal → Adapter → Order → Matcher → Fill" 的单向链路，能很好地支持"逐 bar 决策、下一 bar 撮合"的策略。但实际业务里出现了几类需求，现有契约支持不充分：

1. **开仓预挂单** — 在信号尚未完全确认时提前挂限价单进场，并在信号变化时撤回
2. **平仓预挂单（限价止盈）** — 持仓存在时挂限价平仓单做止盈，未触达时可能要撤回
3. **同方向多挂单并存** — 分批挂出 N 笔同方向限价单，分别成交、分别撤销
4. **挂单中途撤回** — 策略在 `on_bar` 内根据最新信号决定撤掉某些尚未成交的挂单

讨论后达成的设计原则：

| 原则 | 含义 |
| --- | --- |
| **机制 vs 业务分离** | 框架只提供"挂、撤、撮合"机制；资金管理 / 数量校验 / 持仓对应由策略自治 |
| **`client_order_id` 由策略生成 + 框架管控** | 策略侧 ID，但通过 `self.new_client_order_id()` 由框架统一分配，保证全局唯一并符合交易系统规则 |
| **Price-Time 优先撮合** | 多挂单的成交顺序贴近实盘交易所撮合规则 |
| **零侵入升级** | 默认值保持向后兼容；不调用新 API 的老策略行为完全不变 |

## 2. 现状盘点

经过对现有代码的核查，部分能力其实已经具备：

| 能力 | 当前是否支持 | 备注 |
| --- | --- | --- |
| 一个 symbol 同时多个 pending 订单 | **数据结构已支持** | `Matcher._pending: Dict[str, List[_PendingOrder]]` 早已是列表形式 |
| `Order.order_id`（系统内部订单号） | **已存在** | 在 `BasePortfolioAdapter._make_order` 由 `uuid.uuid4().hex[:8]` 生成 |
| `FILL_CANCELLED` 状态 | **常量已定义** | `framework/types.py` 已有 `FILL_CANCELLED = "cancelled"`，但无任何代码产生它 |
| 限价单成交规则 | **已支持** | `_limit_touched` 按 `bar.[low, high]` 触达判定 |
| 限价单超时过期 | **已支持** | `limit_max_wait_bars`（默认 20）后自动 `FILL_EXPIRED` |
| 撮合优先级排序 | ❌ 未支持 | `match_at` 按 list 插入顺序遍历，无价格优先 |
| 主动撤单 API | ❌ 未支持 | Matcher / Strategy / Engine 全链路都没有 `cancel` 接口 |
| 策略侧业务订单标识 | ❌ 未支持 | `Signal.tag` 是 `close_reason` 自由文本，不适合做订单标识 |

## 3. 命名约定

为避免概念混淆，先明确两个 ID：

| 名称 | 含义 | 谁生成 | 在哪些类里 |
| --- | --- | --- | --- |
| `order_id` | 框架内部订单号（已存在） | 框架（`Adapter._make_order` 时 uuid） | Order / Fill |
| `client_order_id` | **策略侧订单号（新增）** | 策略调用 `self.new_client_order_id()`（框架统一分配） | Signal / Order / Fill |

**核心语义：**

- 策略撤单时使用 `client_order_id`（自己最熟悉的业务级标识）
- `client_order_id` 必须通过 `self.new_client_order_id(prefix="")` 获取，不允许策略自己拼字符串
- 框架在 `new_client_order_id` 内部保证：
  - **全局唯一**：跨策略 / 跨 symbol / 跨进程不会冲突
  - **符合实盘规则**：长度 ≤ 21 字节、纯 ASCII（兼容 CTP `OrderRef` 限制）
  - **可读**：包含可选的 `prefix` 用于调试 / 日志

> **与实盘 CTP 的对应关系**
>
> | 本框架 | CTP 协议 | 含义 |
> |---|---|---|
> | `client_order_id` | `OrderRef` | 客户端订单引用（前置生成） |
> | `order_id` | `OrderSysID` | 交易所订单号 |
> | `signal_id` | （框架内部） | 用于回测对账，与 CTP 无对应 |

## 4. 改动总览

| 模块 | 改动量 | 内容 |
| --- | --- | --- |
| `framework/types.py` | 小 | `Signal` / `Order` / `Fill` 各加一个 `client_order_id` 字段 |
| `framework/base.py` | 小 | `Strategy` 新增 `new_client_order_id()` + `cancel_order()` + `_pending_cancels` + `_drain_cancels()` |
| `core/matcher.py` | 中 | 新增 `cancel(symbol, client_order_id)`；`submit_pending` 增加 `client_order_id` 唯一性校验；`match_at` 增加价格-时间优先级排序 |
| `core/engine/loop.py` | 小 | `_step_bar` 五阶段调整；稀疏路径同步加 drain_cancels 步骤 |
| `core/portfolio_adapter.py` | 小 | `Signal.client_order_id` 透传到 `Order.client_order_id` |
| `core/engine/signal_pipeline.py` | 无 | 不需要改 |
| `core/accounting.py` | 无 | `FILL_CANCELLED` 不产生 trade 记录，`TradeAccountant` 已正确忽略 |

## 5. 详细设计

### 5.1 数据结构（`framework/types.py`）

```python
@dataclass(frozen=True)
class Signal:
    ...
    # ---- 新增 ----
    # 策略侧订单号。必须由 self.new_client_order_id(prefix=...) 获取，
    # 而非策略自己拼字符串，以确保全局唯一并符合交易系统规则。
    # 同一 symbol 下未成交挂单的 client_order_id 必须唯一；重复时
    # Matcher.submit_pending 会抛 ValueError 中断本 bar（fail-fast）。
    # 不打算撤单的策略可以省略不填（默认 None）。
    client_order_id: Optional[str] = None
    ...

@dataclass(frozen=True)
class Order:
    ...
    client_order_id: Optional[str] = None  # 透传自 Signal

@dataclass(frozen=True)
class Fill:
    ...
    client_order_id: Optional[str] = None  # 透传自 Order
```

`FILL_CANCELLED` 常量已存在，无需改动。`Order.order_id` 已存在，仍作为系统内部订单号继续使用。

### 5.2 Strategy 基类（`framework/base.py`）

新增 3 个公共 API + 1 个内部方法：

```python
import os
import threading
import time
from typing import List, Optional, Tuple

class Strategy:

    # 类级（进程内）自增计数器
    #   - 同一进程内多策略实例共享，线程安全
    #   - multiprocessing spawn 子进程会重置为 0；不影响全局唯一性，
    #     因为 ID 还混入了 pid 后 4 位 + 时间纳秒后 6 位作为跨进程区分度
    _cid_global_lock = threading.Lock()
    _cid_global_counter = 0

    def __init__(self, ...):
        ...
        self._pending_cancels: List[Tuple[str, str]] = []  # [(symbol, client_order_id)]

    # ── 新增 API：生成 client_order_id ───────────────────────────────

    def new_client_order_id(self, prefix: str = "") -> str:
        """
        生成框架保证全局唯一的 client_order_id。

        交易系统规则（兼容 CTP OrderRef）：
            - 全局唯一（含跨策略、跨进程的回测/实盘场景）
            - 长度 ≤ 21 字节
            - 仅 ASCII 字母/数字（不含下划线 / 特殊字符 / 中文）
            - 全大写

        格式（回测）：
            base36(进程pid 后 4 位 + 全局自增计数器 + 时间纳秒后 6 位)
            例：A0F1Q2R3S4    （10 字节）

        prefix 参数:
            可读性辅助。如果传了 prefix，会以 `{PREFIX_UPPER}{base}` 拼出，
            截断到 21 字节，仅做调试 / 日志用，不影响唯一性
            例：new_client_order_id("open") → "OPENA0F1Q2R3S4"
            建议 prefix ≤ 8 字符，且仅 ASCII 字母/数字

        实盘部署时：
            实盘端可以重写本方法，改用经纪商分配的 OrderRef 池或 trading_day +
            自增序号。接口签名保持一致即可。
        """
        with Strategy._cid_global_lock:
            Strategy._cid_global_counter += 1
            seq = Strategy._cid_global_counter
        # base36 编码使其紧凑且仅含 [0-9A-Z]
        body = self._b36(os.getpid() & 0xFFFF) + self._b36(seq) + self._b36(int(time.time_ns()) & 0xFFFFF)
        body = body.upper()[:21]
        if prefix:
            head = "".join(c for c in prefix.upper() if c.isalnum())[:8]
            body = (head + body)[:21]
        return body

    @staticmethod
    def _b36(n: int) -> str:
        if n == 0:
            return "0"
        digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        out = []
        while n:
            n, r = divmod(n, 36)
            out.append(digits[r])
        return "".join(reversed(out))

    # ── 新增 API：撤单 ────────────────────────────────────────────────

    def cancel_order(self, symbol: str, client_order_id: str) -> None:
        """
        请求撤掉该 symbol 下指定 client_order_id 的挂单。

        - 仅在 on_bar / on_day_end 内调用有意义；引擎在收完信号后统一处理。
        - 撤单成功会以 FILL_CANCELLED 状态触发一次 on_fill。
        - 若该 client_order_id 已成交、已过期、不存在，本次撤单静默忽略。
        - 同一 bar 内可调用多次撤多笔。
        """
        self._pending_cancels.append((symbol, client_order_id))

    # ── 框架内部 ──────────────────────────────────────────────────────

    def _drain_cancels(self) -> List[Tuple[str, str]]:
        cancels, self._pending_cancels = self._pending_cancels, []
        return cancels
```

> **为什么强制经由 `new_client_order_id` 而不是让策略自由填字符串？**
>
> 1. 实盘对 ID 字符集和长度有硬约束（CTP OrderRef ≤ 21 字节、不含特殊字符），策略自由填很容易踩雷
> 2. 多策略 / 多进程并发时，如果各自拼"业务标签"作 ID 极易冲突
> 3. 框架统一分配后，回测和实盘语义完全一致，策略代码无需感知运行环境
> 4. 策略侧仍保留可读性：通过 `prefix` 参数加业务前缀

### 5.3 Matcher 升级（`core/matcher.py`）

#### 5.3.1 `submit_pending` 增加唯一性校验

`client_order_id` 由 `new_client_order_id()` 统一分配，正常情况下**不可能**重复。出现重复 = 策略代码 bug（典型场景：策略把某个 cid 缓存复用、或绕过 `new_client_order_id` 自己拼字符串）。

为了让 bug 第一时间暴露，框架采用 **fail-fast** 策略：检测到重复 → 立即抛 `ValueError` 打断回测：

```python
def submit_pending(self, orders, ts):
    immediate_fills = []

    # 第一遍扫描：唯一性校验（fail-fast）
    seen_in_batch: Dict[str, set] = defaultdict(set)
    for o in orders:
        if o.order_type == ORDER_EXACT or o.client_order_id is None:
            continue
        cid = o.client_order_id

        # 与已 pending 的对比
        if any(po.order.client_order_id == cid for po in self._pending[o.symbol]):
            raise ValueError(
                f"重复 client_order_id: symbol={o.symbol} cid={cid} "
                f"strategy={o.strategy_id}（同 symbol 下已存在未成交挂单；"
                f"请用 self.new_client_order_id() 生成新 ID，"
                f"不要复用旧 ID，也不要自己拼字符串）"
            )
        # 与本批次内的对比
        if cid in seen_in_batch[o.symbol]:
            raise ValueError(
                f"重复 client_order_id: symbol={o.symbol} cid={cid} "
                f"strategy={o.strategy_id}（同一批 Signal 内出现两次相同 cid）"
            )
        seen_in_batch[o.symbol].add(cid)

    # 第二遍：正式入队 / 立即成交
    for o in orders:
        if o.order_type == ORDER_EXACT:
            immediate_fills.append(self._fill_exact(o))
        else:
            self._pending[o.symbol].append(_PendingOrder(order=o, submit_ts=ts))

    return immediate_fills
```

> **为什么用异常而非 reject Fill？**
>
> - `new_client_order_id` 保证全局唯一，所以重复 = 策略代码 bug，不是市场拒单
> - 软处理（reject Fill）可能被策略 `on_fill` 吞掉，bug 被隐藏到 PnL 失真才被发现
> - 硬中断（raise）让 bug 立即暴露在 `errors` 列表里，便于第一时间修复
> - 与"市场层正常拒单"（如保证金不足）的语义清晰分离

#### 5.3.2 撤单接口

```python
def cancel(self, symbol: str, client_order_id: str) -> Optional[Fill]:
    """
    撤回 symbol 下指定 client_order_id 的 pending 单。

    - 找到匹配单：从 _pending[symbol] 移除，返回 FILL_CANCELLED 的 Fill
    - 找不到（已成交/已过期/ID 不存在）：返回 None，不抛异常
    """
    pending_list = self._pending.get(symbol, [])
    for i, po in enumerate(pending_list):
        if po.order.client_order_id == client_order_id:
            order = po.order
            del pending_list[i]
            return Fill(
                fill_id          = uuid.uuid4().hex[:8],
                order_id         = order.order_id,
                signal_id        = order.signal_id,
                strategy_id      = order.strategy_id,
                symbol           = order.symbol,
                contract         = order.contract,
                status           = FILL_CANCELLED,
                fill_datetime    = None,
                fill_price       = None,
                fill_volume      = 0,
                direction        = order.direction,
                offset           = order.offset,
                commission       = 0.0,
                session          = order.session,
                client_order_id  = order.client_order_id,
                reject_reason    = "cancelled by strategy",
                tag              = order.tag,
            )
    return None
```

#### 5.3.3 价格-时间优先撮合

`match_at` 在遍历 `_pending[symbol]` 之前先做一次稳定排序：

| 订单类型 | 排序键 |
| --- | --- |
| 买单（`direction == 1`） | `(-price, submit_ts)` — 限价高的先成交 |
| 卖单（`direction == -1`） | `(price, submit_ts)` — 限价低的先成交 |
| 市价 / 止损 | 排序顺序与原列表一致（按提交先后） |

实现要点：

- 买卖单分桶后各自排序，再合并遍历，避免相互污染
- 同价同方向的多笔，按 `submit_ts` 早的先撮合（`_PendingOrder.submit_ts` 已存在 ✓）
- 现有"超时过期"逻辑保持不变

### 5.4 Engine 主循环（`core/engine/loop.py`）

`_step_bar` 现有四阶段改为五阶段：

```
1. matcher.match_at(bar)
       撮合上一 bar 提交的 pending 订单 → handle_fill

2. strategy.on_bar(bar, snapshot)
       策略决策；可调用 self.cancel_order(symbol, cid) 累积撤单请求
       策略 return signals

3. ★ 新增：处理 strategy._drain_cancels()
       逐个调用 matcher.cancel(symbol, cid)
       撤单成功的 Fill (FILL_CANCELLED) → handle_fill
       触发 strategy.on_fill，让策略更新自己的 pending 状态

4. tag_signal + adapter.process(signals) → orders
       生成 Order，client_order_id 透传

5. matcher.submit_pending(orders, ts) → immediate_fills
       新挂单入队（ORDER_EXACT 立即成交并触发 on_fill；
                    重复 client_order_id 立即 raise ValueError 中断本 bar）
```

关键顺序保证：

- **撤单在新挂单之前** — 同 bar 内"撤旧挂新"语义清晰
- **on_fill(FILL_CANCELLED) 在新单挂出之前** — 策略可在 on_fill 里更新 pending 状态，但不影响本 bar 已经决策好的新挂单（因为 on_bar 已结束）

### 5.5 PortfolioAdapter 透传（`core/portfolio_adapter.py`）

`BasePortfolioAdapter._make_order` 透传 `client_order_id`：

```python
return Order(
    ...
    client_order_id = signal.client_order_id,  # ← 新增
)
```

三个 Adapter 实现都通过 `_make_order` 走，所以只改基类一处。

## 6. 各运行路径覆盖

| 路径 | 撤单支持 | 备注 |
| --- | --- | --- |
| `_run_single_symbol` | ✅ `_step_bar` 自动覆盖 | 单品种标准路径 |
| `_run_multi_symbol` | ✅ `_step_bar` 自动覆盖 | 多品种全 universe |
| `_run_each_symbol(sparse=False)` | ✅ 内部调 `_step_bar` | 多品种独立顺序 |
| `_run_single_symbol_sparse` | ✅ 不适用 | 见下文论证 |
| `_run_each_symbol(sparse=True)` | ✅ 不适用 | 委托给稀疏路径 |

### 关于稀疏批量预算路径与回测/实盘统一性

**先澄清概念**：稀疏路径**仅是回测的性能优化**，不是策略行为差异。

- 实盘**没有**"稀疏路径"概念 —— 实盘所有策略都是逐 bar 调 `on_bar`（实盘按 bar 接收行情，不可能提前知道未来）
- 回测的稀疏路径是利用"提前知道所有数据"的特性，让策略在 `on_init` 阶段一次性算完所有信号，运行时跳过无动作 bar
- 同一份策略代码必须在两种模式下产出**完全相同**的回测/实盘结果，否则就违反"回测实盘一致"原则

**因此撤单能力在两个模式下的"统一"是这样实现的：**

| 策略类型 | 实盘模式 | 回测模式 | 撤单 |
| --- | --- | --- | --- |
| 不需要撤单的策略（如当前 6 个） | 逐 bar `on_bar` | 可选稀疏快路径 | 不涉及 |
| 需要撤单的策略 | 逐 bar `on_bar` | **必须**走标准 `on_bar` 路径 | ✅ 支持 |

也就是说：**需要 `cancel_order` 的策略必须设 `SUPPORTS_BATCH_PREBUILD = False`，回测和实盘都走 `on_bar` 路径**——两端行为完全一致，符合"统一"要求。

**为什么不让稀疏路径也支持撤单？** 因为这是个伪命题：

- 稀疏路径的本质是"信号在 `on_init` 阶段全部预算完毕，运行时不调 `on_bar`"
- 撤单语义是"运行时根据新信息改变主意"
- 让稀疏路径支持撤单 = 让策略在 `on_init` 里就预知"未来在 ts=X 要撤掉 cid=Y"
- 这种"预算阶段就排好的撤单"等价于"信号根本没生成" —— 直接在批量预算里改信号集合就行，根本不需要"撤单"语义

**校验机制（防误用）：**

稀疏路径根本不调 `on_bar`，所以策略正常情况下也没机会调 `cancel_order`。但如果策略在 `on_init` / `on_day_end` 等钩子里误调了 `cancel_order`，需要让错误第一时间暴露。

引擎在 `_run_single_symbol_sparse` 的每次 ts 迭代之后（在 `for sig_ts in sorted(batch_signals.keys()):` 循环体末尾）做一次检查：如果某个 slot 的 `_pending_cancels` 非空，抛 `RuntimeError`：

```
策略 {strategy_id} 走了稀疏批量路径，但调用了 cancel_order；
请设置 SUPPORTS_BATCH_PREBUILD = False，让回测走标准 on_bar 路径以保持与实盘一致。
```

> **为什么不在 `on_init` 之后立即检查？** —— 因为 `on_init` 里调 `cancel_order` 是无意义但无害的（此时没任何 pending 单），等到第一次迭代时再检查既能覆盖这种情况，也能覆盖后续误调用。

## 7. 策略侧使用模式

### 7.1 典型用例：开仓预挂单 + 中途撤回

```python
class MyStrategy(framework.Strategy):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._open_pending: Dict[str, dict] = {}  # client_order_id → 业务状态

    def on_bar(self, bar, snapshot):
        signals = []

        if self._should_pre_place_long(bar):
            for i, lvl in enumerate(self._entry_levels(bar)):
                cid = self.new_client_order_id(prefix=f"OL{i}")  # ← 框架分配
                self._open_pending[cid] = {"price": lvl, "qty": 1}
                signals.append(Signal(
                    symbol           = bar.symbol,
                    action_datetime  = bar.timestamp,
                    bar_datetime     = bar.timestamp,
                    signal_kind      = SIGNAL_ENTRY,
                    direction        = +1,
                    offset           = OFFSET_OPEN,
                    order_type       = ORDER_LIMIT,
                    price            = lvl,
                    volume_hint      = 1,
                    session          = "早盘",
                    client_order_id  = cid,
                ))

        # 信号反转，撤回所有未成交的开仓单
        if self._signal_reversed(bar):
            for cid in list(self._open_pending):
                self.cancel_order(bar.symbol, cid)
                # 不在这里 del；等 on_fill(FILL_CANCELLED) 来再清理

        return signals

    def on_fill(self, fill):
        super().on_fill(fill)  # 必须保留，自动维护 self.position

        cid = fill.client_order_id
        if cid and cid in self._open_pending:
            if fill.status in (FILL_FILLED, FILL_CANCELLED, FILL_EXPIRED, "rejected"):
                # 任何终态都从 pending 字典里清理掉
                self._open_pending.pop(cid, None)
```

### 7.2 平仓限价止盈（持仓已存在）

```python
def __init__(self, ...):
    super().__init__(...)
    self._tp_long_cid: Optional[str] = None

def on_bar(self, bar, snapshot):
    signals = []

    if self.position.long_volume > 0 and self._tp_long_cid is None:
        cid = self.new_client_order_id(prefix="TPL")
        self._tp_long_cid = cid
        tp_price = self.position.long_avg_price * 1.02
        signals.append(Signal(
            symbol           = bar.symbol,
            action_datetime  = bar.timestamp,
            bar_datetime     = bar.timestamp,
            signal_kind      = SIGNAL_TAKE_PROFIT,
            direction        = -1,
            offset           = OFFSET_CLOSE,
            order_type       = ORDER_LIMIT,
            price            = tp_price,
            volume_hint      = self.position.long_volume,
            session          = "早盘",
            client_order_id  = cid,
        ))

    # 仓位被止损或反转后撤回未成交的止盈单
    if self.position.long_volume == 0 and self._tp_long_cid is not None:
        self.cancel_order(bar.symbol, self._tp_long_cid)

    return signals

def on_fill(self, fill):
    super().on_fill(fill)
    if fill.client_order_id == self._tp_long_cid:
        if fill.status in (FILL_FILLED, FILL_CANCELLED, FILL_EXPIRED, "rejected"):
            self._tp_long_cid = None
```

### 7.3 自治责任清单

策略侧需要自己保证（框架不校验）：

- [ ] 必须使用 `self.new_client_order_id(prefix=...)` 获取 ID，**不要自己拼字符串**
- [ ] 平仓单的累计 `volume_hint` 不超过持仓的可平数量（包含已挂未成交份额）
- [ ] 开仓单的累计名义价值不超过策略希望承担的资金上限
- [ ] 在 `on_fill` 内根据 `fill.status` 正确清理自己维护的 pending 字典

## 8. 兼容性 / 风险

| 项 | 说明 |
| --- | --- |
| 老策略代码 | 不需要修改：所有新字段默认 `None`；不调用 `new_client_order_id` / `cancel_order` 行为完全不变 |
| 现有回测基线 | 价格-时间优先排序对**单挂单**场景无影响；多挂单当前业务里不存在 — 预期 baseline 100% 不变 |
| `signal_recorder` | 不变；记录的 Signal 多一个 `client_order_id` 列，下游 diff 工具可能需要忽略该列 |
| `tools/compare_baseline.py` | 不变；trade / nav / pnl 都不受影响 |
| `framework/order_book.py` (live) | 建议同步加 `client_order_id` 字段，但不在本次回测升级里 |
| 实盘对接 | `client_order_id` ↔ CTP `OrderRef`，`order_id` ↔ CTP `OrderSysID`；实盘可重写 `new_client_order_id` 改用经纪商分配池，接口签名一致 |

## 9. 不做什么（明确边界）

- ❌ 框架级"挂单占用资金"管理 — 由策略自己控制
- ❌ 平仓单与持仓数量的强制校验 — 由策略自己控制
- ❌ 多笔挂单的资金累加上限 — 由策略自己控制
- ❌ Bar 内成交量约束（不超过 `bar.volume × 比例`）
- ❌ `ORDER_STOP` 真正的止损单语义（仍按市价处理）
- ❌ `ConflictDedupAdapter` 的真正净额化（保持现状）
- ❌ 让稀疏批量预算路径支持运行时撤单（伪命题；需要撤单的策略走标准 `on_bar` 路径）
- ❌ 策略自由拼字符串作 `client_order_id`（必须经 `new_client_order_id`，重复 → `ValueError`）

## 10. 实施步骤（参考）

预估总工作量 **0.5 ~ 1 人日**，全部为框架内部改动，无业务策略改动。

1. **数据契约**：`framework/types.py` 三个 dataclass 加 `client_order_id: Optional[str] = None`
2. **Adapter 透传**：`core/portfolio_adapter.py` `_make_order` 透传 `client_order_id`
3. **Strategy 接口**：`framework/base.py` 加 `new_client_order_id()` / `cancel_order()` / `_drain_cancels()` / `_pending_cancels` / `_b36` 静态方法 + 类级计数器
4. **Matcher 撤单**：`core/matcher.py` 加 `cancel(symbol, client_order_id)`
5. **Matcher 唯一性**：`submit_pending` 增加同 symbol `client_order_id` 重复检测，重复 → `raise ValueError`
6. **Matcher 优先级**：`match_at` 循环前对 limit 单按价格-时间排序
7. **Engine 主循环**：`core/engine/loop.py` `_step_bar` 调整为五阶段
8. **回归**：跑 `tests/baseline/` 全部 baseline，期望 100% 不变
9. **新增测试**：`tests/` 加 7 个用例
   - `new_client_order_id` 全局唯一性（多线程压力测试 + 长度 ≤ 21 + 字符集校验）
   - 单挂单撤单成功 → `FILL_CANCELLED`
   - 撤一个不存在的 client_order_id → 静默无 Fill
   - 同方向 3 笔限价开仓单按价格优先成交
   - 同 bar 撤旧挂新（验证执行顺序）
   - 同 symbol 重复 `client_order_id` → `ValueError`
   - 策略在稀疏路径下调用 `cancel_order` → `RuntimeError`
10. **文档更新**：
    - `docs/STRATEGY_CONTRACT.md` 增加 `client_order_id` 字段说明 + `new_client_order_id` / `cancel_order` API
    - `docs/ARCHITECTURE.md` 数据流图里把"撤单"步骤画出来

## 11. 设计决策汇总

经过四轮讨论，最终确认的设计决策：

| # | 决策 | 来源 |
| --- | --- | --- |
| 1 | `client_order_id` 由策略生成，但必须经 `self.new_client_order_id()` 由框架统一分配 | 用户确认 |
| 2 | ID 格式：≤ 21 字节、纯 `[0-9A-Z]`、可选 prefix（兼容 CTP `OrderRef`） | 用户确认 |
| 3 | 同 symbol 下 `client_order_id` 重复 → `ValueError` 中断本 bar（fail-fast） | 用户确认 |
| 4 | `Signal.client_order_id` 对所有 `order_type` 都允许填 | 用户确认 |
| 5 | 需要撤单的策略必须设 `SUPPORTS_BATCH_PREBUILD = False` 走标准 `on_bar` 路径，确保回测/实盘行为一致 | 用户确认 |
| 6 | 资金管理 / 持仓校验 / 多笔挂单累计上限 全部由策略自治，框架不介入 | 用户确认 |
| 7 | 多挂单按 price-time 优先撮合（贴近交易所规则） | 用户确认 |

确认无误后即可按"实施步骤"执行。
