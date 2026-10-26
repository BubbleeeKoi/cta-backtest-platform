# 实盘 drop-in 部署 SOP

## 前提

实盘项目（仓库另立）必须已经实现：
- `LiveDataPool`（继承 `framework.DataPool`，订阅实时行情）
- `LiveOrderRouter`（替代 `core.Matcher`，接 CTP / 经纪商 API）
- `LiveAccountant`（实时记账）
- 实盘的 `run_live.py` 入口

**这些是实盘项目自研，不在本回测项目内**。

## 同源代码同步

每次成员上线新版本：

```bash
# 1) framework/ 整体同步（确保契约一致）
rsync -av --delete \
    cta_strategy_analysis/strategy/framework/ \
    LIVE_PROJECT/strategy/framework/

# 2) 单个成员的策略包（以 jerome 为例）
rsync -av --delete \
    cta_strategy_analysis/strategy/strategies/jerome/ \
    LIVE_PROJECT/strategy/strategies/jerome/

# 3) 项目级元数据
rsync -av \
    cta_strategy_analysis/strategy/data/future_list.csv \
    cta_strategy_analysis/strategy/data/industry_map.csv \
    LIVE_PROJECT/strategy/data/

# 4) 重启该成员的策略进程
ssh prod "supervisorctl restart jerome_strategy"
```

## 实盘项目要做什么

实盘的 `run_live.py` 应该：

```python
from framework import Strategy
from strategies import load_strategy_class
from live import LiveDataPool, LiveOrderRouter, LiveAccountant

StrategyCls = load_strategy_class("jerome")
data_pool = LiveDataPool(symbols=[...])     # 接 CTP 行情订阅

inst = StrategyCls(
    strategy_id="jerome",
    contract_info=future_list_row,
    data_pool=data_pool,
    params={},
)

# 启动时预热
inst.on_init(HistoryView(symbol="RB", own_bars=last_500_bars_df, data_pool=data_pool))

# 实时驱动
@data_pool.on_new_bar
def handle(bar):
    snapshot = build_snapshot(bar, data_pool)
    signals = inst.on_bar(bar, snapshot)
    for sig in signals:
        order = adapter.process_one(sig)        # 等价 PortfolioAdapter
        order_router.send(order)

@order_router.on_fill
def handle_fill(fill):
    inst.on_fill(fill)
    accountant.on_fill(fill)
```

**关键**：`Strategy` / `Signal` / `Fill` / `Bar` 与回测**完全同源**，所以策略代码不用改一行。

## 注意事项

1. 实盘 `LiveDataPool.get_minute_bars` 必须**严格因果**——返回 `as_of` 之前 + 等于 `as_of` 的 bar，不返回未来
2. 实盘的 `on_bar` 频率与策略期望一致（默认 1 分钟）；如成员策略需要不同频率，应在 `__init__` 自己聚合
3. `on_fill` 在实盘是**异步回调**；策略不能假设发单后立刻成交。用 `framework.OrderBook` 跟踪 pending signal_id
4. 风控由实盘项目兜底（最大持仓 / 总仓限额等），策略层无需重复实现
