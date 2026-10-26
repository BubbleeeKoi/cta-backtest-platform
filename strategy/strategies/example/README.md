# jerome · 挂单生命周期演示策略

挂单 / 撤单生命周期演示策略，端到端验证 framework 中
`new_client_order_id` / `cancel_order` / price-time priority 撮合等机制。

不追求绩效，目的是覆盖所有挂单生命周期事件。

## 文件结构

```
jerome/
  __init__.py         re-exports Strategy + STRATEGY_NAME
  strategy.py         框架对接 + on_bar/on_fill 调度（Strategy 类）
  decision.py         入场 / 平仓决策（纯函数；EntryPlan / ExitPlan）
  features.py         滚动指标累加器（IndicatorWindow：mid / ATR / vol_ratio）
  filters.py          入场 / 平仓闸门（check_xxx 纯函数）
  params.py           StrategyParams / CarryState / STRATEGY_NAME / NAV_SESSION_NAMES
  README.md           本文件
```

`strategy.py` 只做框架对接 + 副作用调用（`cancel_order` / `new_client_order_id`
/ 生成 `Signal`）；状态机决策全部下沉到 `decision.py` / `filters.py` 纯函数。

## 公开符号

```python
from strategies.jerome import Strategy, STRATEGY_NAME
from strategies.jerome.params import NAV_SESSION_NAMES  # ["早盘"]
```

## 三类生命周期事件演示

### 1. 开仓预挂单 + 条件撤单

- 09:30 起在 `mid ± k·ATR_short` 多空各挂 `n_legs=3` 层限价单
  - 同方向 N 笔限价单并存（验证 framework 多挂单能力）
  - `client_order_id` 用 `self.new_client_order_id("OL0")` / `("OS0")` 等生成
- 每根 bar 评估 `vol_ratio = ATR_short / ATR_long`：
  - 若 `vol_ratio < vol_shrink_ratio (0.85)` → 撤掉所有未成交入场单
  - 撤单后等 `rebar_interval` 根 bar 才重新挂
- 任一层入场单成交 → 立刻撤掉所有同方向其它层 + 反方向所有层
  - 1 个 fill 触发 N-1 个 cancel_order

### 2. 平仓限价单 + 动态调整重挂

- 入场成交后立即挂一笔 `entry_price ± tp_atr·ATR` 限价止盈单
- 每 `tp_adjust_every_bars` 根 bar 评估：
  - 若浮亏 ≥ `tp_adjust_adverse_ratio·ATR` → 撤旧止盈单，按更接近的价位重挂
  - 最多调整 `tp_adjust_max_times` 次

### 3. 市价止损（撤单后强平）

- 浮亏 ≥ `sl_atr·ATR` 或 持仓 ≥ `sl_max_hold_bars` 根
  → 撤回未成交平仓单 + 立即发市价单平仓

### 14:55 尾盘强平

- 撤所有未成交挂单（入场 + 出场）
- 持仓非空 → 市价强平

## 默认参数（核心）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `observe_start` | 09:30 | 开始挂入场单 |
| `entry_cutoff` | 11:00 | 不再新挂入场单 |
| `close_time` | 14:55 | 尾盘强平 |
| `mid_lookback_bars` | 20 | mid = 最近 N 根 close 均值 |
| `atr_short` / `atr_long` | 10 / 30 | 短/长 ATR 窗口 |
| `n_legs` | 3 | 单方向挂多少层 |
| `leg_step_atr` | 0.6 | 相邻层距离（短 ATR 倍数） |
| `entry_volume` | 1 | 每笔挂单手数（演示用 1 手） |
| `vol_shrink_ratio` | 0.85 | vol_ratio < 此值 → 撤入场单 |
| `rebar_interval` | 10 | 撤单后最小重挂间隔 |
| `tp_atr` | 1.5 | 初始止盈距开仓价（短 ATR 倍数） |
| `tp_adjust_every_bars` | 10 | 调整止盈节流（根 bar） |
| `tp_adjust_adverse_ratio` | 0.5 | 浮亏阈值（短 ATR 倍数） |
| `tp_adjust_step_ratio` | 0.3 | 每次调低多少（短 ATR 倍数） |
| `tp_adjust_max_times` | 3 | 最多调整次数 |
| `sl_max_hold_bars` | 60 | 持仓超时阈值（根 bar） |
| `sl_atr` | 2.0 | 浮亏强平阈值（短 ATR 倍数） |

完整参数表见 `params.py:StrategyParams`。

`SUPPORTS_BATCH_PREBUILD = False`（**必须**）：用了 `cancel_order` 的策略
不能走稀疏批量预算路径，回测必须沿 `on_bar` 真增量路径运行。

## 运行与可观测性

```bash
# 单策略单品种快速验证
python strategy/run_backtest.py \
    --strategy jerome --symbols RB \
    --start 2024-01-01 --end 2024-06-30
```

输出文件:

| 文件 | 用途 |
|---|---|
| `output/trades/trades_jerome.csv` | 成交流水（close_reason 体现策略意图）|
| `output/signals/signals_jerome.csv` | 策略发出的全部 Signal |
| `output/actions/actions_jerome.csv` | **动作事件流**：每一次 `place_order` / `cancel_request` / `fill_*`，可视化挂单生命周期全过程 |
| `output/daily/...` | 净值 |

`actions_*.csv` 是验证挂单 / 撤单机制是否正常工作的关键产物。
事件类型:

- `place_order`：策略发出一笔 order，进入 matcher
- `cancel_request`：策略调 `cancel_order(cid)`
- `fill_filled` / `fill_cancelled` / `fill_expired` / `fill_rejected`：撮合层反馈
- `pending_after` 列展示该 symbol 当前 pending 队列长度，便于看"同方向多笔并存"瞬间
