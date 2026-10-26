# 策略契约

每个成员的 `strategies/<member>/` 必须符合本契约，否则无法被引擎发现/加载。

## 目录结构（最小）

```
strategies/<member>/
├── __init__.py            必填：from .strategy import Strategy
├── strategy.py            必填：导出名为 Strategy 的类
├── config.yaml            可选：私有参数；按需自己 yaml.safe_load
├── README.md              可选：策略说明
└── <其它私有模块>.py        可选；只能用相对导入引用
```

**禁止**：
- 引用其它成员的目录（`from strategies.xxx import ...`）
- 直接读 .h5 / .csv 数据；所有跨品种数据走 `self.data_pool`
- 修改 `framework/` 或 `core/` 任何代码
- 使用绝对路径

## 必须的类属性

```python
class Strategy(framework.Strategy):
    REQUIRED_UNIVERSE = "sector"   # "self" | "sector" | "all" | ["RB", "MA", ...]
    SESSION_NAMES = ["早盘"]        # 参与 NAV 分组的时段名（与本策略发出的 Signal.session 严格一致）
```

`SESSION_NAMES` 的字符串由本策略包自行定义（通常在 `params.py` 中以 `NAV_SESSION_NAMES` 暴露），与本策略 `Signal.session` 字段写入的字符串一一对应即可——`core.accounting.nav_dataframe` 仅按 `(strategy_id, session)` 元组聚合 daily_pnl，不做跨策略字符串校验。

本分发版示例策略 `jerome` 的取值：

| 策略 | `NAV_SESSION_NAMES` |
|---|---|
| jerome | `["早盘"]` |

`REQUIRED_UNIVERSE` 选项：

| 选项 | 含义 |
| --- | --- |
| `"self"` | 仅依赖自身品种数据；Snapshot 内只放自己 |
| `"sector"` | 依赖同板块全部品种；用 `snapshot.peers_in_sector()` 拿同板块 |
| `"all"` | 依赖全市场 universe；用 `self.data_pool.list_universe()` |
| `[...]` | 显式列出依赖品种 |

## 必须实现的方法

```python
def on_init(self, history: HistoryView) -> None:
    """预热钩子。回测：传入 warmup_bars 根历史；实盘：拉取最近 N 日历史。
    history.own_bars             # pd.DataFrame，自己品种的预热数据
    history.data_pool            # 用于查其它品种历史
    """

def on_bar(self, bar: Bar, snapshot: Snapshot) -> list[Signal]:
    """每根 bar 调用一次。返回本根 bar 触发的 Signal 列表。
    bar.symbol / .timestamp / .open / .high / .low / .close / .volume / .tradingday
    snapshot.get_bar(other_symbol)   # 取同 ts 上其它品种的 bar
    snapshot.peers_in_sector()       # 同板块品种列表
    """

def on_fill(self, fill: Fill) -> None:
    """成交回报。框架默认自动更新 self.position；如自己覆盖务必调 super()。"""
    super().on_fill(fill)            # 必须保留这一行

def on_day_end(self, td) -> list[Signal]:
    """日终钩子（可选）。"""
    return []
```

## Signal 字段约定

```python
Signal(
    symbol           = bar.symbol,           # 自动从 bar 取
    action_datetime  = bar.timestamp,        # 信号实际产生时刻（实盘=now，回测=bar.timestamp）
    bar_datetime     = bar.timestamp,        # 触发本信号的 bar 时间戳
    signal_kind      = SIGNAL_ENTRY,         # entry / exit / stop_loss / take_profit / force_close
    direction        = +1,                    # +1 多 / -1 空
    offset           = OFFSET_OPEN,           # open / close / close_today / close_yesterday
    order_type       = ORDER_MARKET,          # market / limit / stop
    session          = "早盘",                 # 必须在 self.SESSION_NAMES 内
    tag              = "突破信号",            # 自由文本，进入 trades.csv 的 close_reason
    price            = None,                  # market 单可空；limit 单必填
    client_order_id  = self.new_client_order_id("OL"),  # 撤单 / 业务对账用；详见下节
)
```

**不要填**：`signal_id` / `strategy_id`——框架在调度时自动注入。

## 挂单 / 撤单 API（仅 ORDER_LIMIT 等进入 pending 队列的订单需要）

策略可以挂限价单、再根据信号变化撤回；支持同方向多笔挂单并存。详见
[docs/PENDING_ORDER_UPGRADE.md](PENDING_ORDER_UPGRADE.md)。

```python
def on_bar(self, bar, snapshot):
    # 1. 生成框架统一分配的 client_order_id（保证全局唯一 / 长度 ≤ 21 / 仅 [0-9A-Z]）
    cid = self.new_client_order_id(prefix="OL")    # prefix 可选，仅供调试可读

    # 2. 同步建立业务映射，便于后续撤单 / on_fill 对账
    self._open_pending[cid] = {...}

    # 3. 发出 limit 单，client_order_id 透传
    signals.append(Signal(..., order_type=ORDER_LIMIT, client_order_id=cid))

    # 4. 同 bar 内可基于新信号撤掉某笔挂单
    if should_cancel:
        self.cancel_order(bar.symbol, cid)   # 框架在 on_bar 结束后立刻 drain

    return signals

def on_fill(self, fill):
    super().on_fill(fill)
    cid = fill.client_order_id
    if cid and cid in self._open_pending:
        # FILL_FILLED / FILL_CANCELLED / FILL_EXPIRED / "rejected" 都是终态
        if fill.status in (FILL_FILLED, FILL_CANCELLED, FILL_EXPIRED, "rejected"):
            self._open_pending.pop(cid, None)
```

**关键规则：**

- `client_order_id` 必须用 `self.new_client_order_id()` 生成，**不要自己拼字符串**（保证唯一 / 符合 CTP 实盘约束）
- 同一 symbol 下未成交挂单的 `client_order_id` 必须唯一；重复 → `ValueError`
- 多笔挂单按 price-time priority 撮合（价格优先，同价按提交时间）
- 资金管理、平仓数量、累计名义价值 全部由策略自治，框架不强制
- 使用 `cancel_order` 的策略必须设 `SUPPORTS_BATCH_PREBUILD = False`（稀疏批量预算路径不支持运行时撤单；回测和实盘需统一走 `on_bar` 路径）

## 仓位查询

```python
self.position.long_volume      # 当前多头手数
self.position.short_volume     # 当前空头手数
self.position.net_volume       # 净仓（多 - 空）
self.position.is_flat          # 是否空仓
self.position.long_avg_price   # 多头均价
```

`self.position` 在 `super().on_fill(fill)` 内自动维护。**永远不要**自己 `self.position.long_volume = 5`。

## 错误示例

❌ **不要**:

```python
class MyStrategy:                      # 必须继承 framework.Strategy
class Strategy(BaseStrategy):
    def on_bar(self, bar):             # snapshot 参数必填
class Strategy(framework.Strategy):
    REQUIRED_UNIVERSE = "all"
    def on_bar(self, bar, snapshot):
        df = pd.read_hdf("RB.h5")     # 禁止直接读盘；走 self.data_pool
```

✅ **正确**:

```python
from framework import Strategy as BaseStrategy
from .params import NAV_SESSION_NAMES

class Strategy(BaseStrategy):
    REQUIRED_UNIVERSE = "sector"
    SESSION_NAMES = list(NAV_SESSION_NAMES)

    def on_bar(self, bar, snapshot):
        peers = snapshot.peers_in_sector()
        ...
```
