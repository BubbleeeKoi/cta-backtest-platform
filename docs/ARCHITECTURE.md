# 架构总览

## 设计原则

> **回测代码与实盘代码共用同一份 `framework/`，策略包 `strategies/<member>/` 原样部署到实盘。**

由此推导出三层分离：

| 层 | 目录 | 实盘是否复制 | 责任 |
| --- | --- | --- | --- |
| 契约层 | `strategy/framework/` | ✅ 必须 | 策略 / 信号 / 订单 / 成交的数据类与接口 |
| 引擎层 | `strategy/core/` | ❌ 不复制 | 仅回测；驱动 bar 流 + 撮合 + 记账 |
| 策略层 | `strategy/strategies/` | ✅ 单个成员目录 | 团队成员业务代码 |

实盘项目自行实现 `LiveDataPool` / `LiveMatcher` / `LiveAccountant`，但它们的**接口签名**必须与 `core/` 一致——以 `framework/` 中定义的 `DataPool` 抽象、`Order` / `Fill` 数据类为锚点。

## 数据流

```
   行情源             策略层              组合层               撮合层              记账层
   ┌────┐  Bar    ┌──────────┐ Signal ┌──────────────┐ Order ┌────────┐ Fill ┌────────────┐
   │data│────────▶│ Strategy │───────▶│ Portfolio    │──────▶│Matcher │─────▶│ Accountant │
   │Pool│         │ on_bar() │        │ Adapter      │       │        │      │            │
   └────┘         └─────┬────┘        └──────────────┘       └────────┘      └─────┬──────┘
                        │             (passthrough/                                 │
                        │              capped/dedup)                                ▼
                        │                                                  trades.csv + nav.csv
                        ▼
                    on_fill(fill)  ◀─────────────────────────────────────── 反馈成交
```

### 三个边界对象

| 对象 | 谁产生 | 谁消费 | 关键字段 |
| --- | --- | --- | --- |
| `Signal` | 策略 | PortfolioAdapter | symbol / direction / offset / signal_kind / 不含手数 / 不含合约 |
| `Order` | PortfolioAdapter | Matcher | + volume / contract |
| `Fill` | Matcher | Strategy.on_fill + Accountant | status / fill_price / fill_volume / commission |

**策略不感知 Order / 不挑手数 / 不挑合约**——这正是回测和实盘可以共用策略代码的核心原因。

## 时间游标（回测，五阶段）

```
for ts in timeline:                          # universe 所有品种 timestamp 的并集
    for sym, bar in ts_bars(ts):
        # 1. 撮合上一根 bar 提交的 pending 订单（含 price-time priority）
        fills = matcher.match_at(bar)
        for f in fills:
            strategy.on_fill(f)
            accountant.on_fill(f)
    for sym, bar in ts_bars(ts):
        # 2. 策略决策；可调用 self.cancel_order(symbol, cid) 累积撤单请求
        signals = strategy.on_bar(bar, snapshot)
        ...
    # 3. drain_cancels：处理 on_bar 内累积的撤单 → FILL_CANCELLED → on_fill
    for slot in slots:
        for sym, cid in slot.instance._drain_cancels():
            f = matcher.cancel(sym, cid)
            if f: handle_fill(f)
    # 4. 组合层加工 Signal → Order（client_order_id 透传）
    orders = adapter.process(signals)
    # 5. 新挂单入队（ORDER_EXACT 立即成交；重复 client_order_id → ValueError）
    matcher.submit_pending(orders, ts)
```

市价单语义 = "下一根 bar 收盘成交"。

挂单 / 撤单语义见 [docs/PENDING_ORDER_UPGRADE.md](PENDING_ORDER_UPGRADE.md) 与 [docs/STRATEGY_CONTRACT.md](STRATEGY_CONTRACT.md) "挂单 / 撤单 API" 节。

## 多策略组合调度

每个 `(strategy, symbol)` 是一个独立的 `StrategySlot`：
- 6 个成员 × 平均 30 个品种 ≈ 180 个槽位
- 单次 `on_bar` 调度复杂度 O(slots)，瓶颈是 Python 解释器而非数据
- 实测 ~6000 bar/秒（含 1 个策略 1 个品种），随槽位数线性下降

## 进程内 vs 跨进程

当前为单进程内顺序调度。未来可：
- 把每个策略包跑在独立进程（multiprocessing.Pool）
- 在 adapter 层做进程间 Signal 聚合
- 暂未实现，因为 Python 全局解释器锁对 numpy / pandas 已天然释放
