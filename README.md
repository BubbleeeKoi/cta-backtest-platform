# CTA 回测平台

本仓库包含 CTA 回测框架、策略实现、绩效报告、批量回测入口，以及通过
Git LFS 管理的 74 个商品指数 HDF5 行情文件。当前批量入口会运行前四类中
已经适配的 69 个单品种策略。

## 你能用它做什么

- 一条命令批量回测 69 个策略、74 个品种，支持 `15m`、`1h`、`1d`
- 分别选择 `long`、`short` 或 `both` 交易方向
- 输出交易、信号、动作、每日盈亏、权益曲线、绩效报告与深度评价
- 在 `framework/` 契约层之上实现和接入新策略
- 用 `tests/` 下的测试做回归保护

## 快速开始

```powershell
# 1) 克隆时同时取得 Git LFS 行情文件
git lfs install
git clone <仓库地址>
cd <仓库目录>
git lfs pull

# 2) 安装运行依赖
D:\anaconda3\python.exe -m pip install -r requirements.txt

# 3) 运行测试（可选）
D:\anaconda3\python.exe -m pytest -q

# 4) 批量运行：69 个策略 × 多空双向 × 日线 × 全部 74 个品种，并生成图片
cd strategy
D:\anaconda3\python.exe -u batch_single_product_backtest.py --directions both --timeframes 1d --plots
```

命令默认读取仓库内的 `data/future_price/*.h5`，日期范围由
`strategy/config/date_range.yaml` 控制，输出写入 `strategy/output/`。批量任务按策略
串行执行，成功任务带有批次指纹，命令中断后再次执行会跳过同批次已完成结果。

跑完后产物落到 `strategy/output/`：

| 文件 | 内容 |
| --- | --- |
| `trades/trades_<prefix>.csv` | 成交流水（含 close_reason） |
| `signals/signals_<prefix>.csv` | 策略发出的全部 Signal |
| `actions/actions_<prefix>.csv` | **动作事件流**：每一次 place_order / cancel_request / fill_*；用来核查挂单 → 撤单 → 成交全过程 |
| `daily/symbol/daily_pnl_<prefix>.csv` | 品种每日净值 |
| `capital/capital_daily_<prefix>.csv` | 每个策略 × 品种的逐日盯市权益（含已实现和未实现盈亏） |
| `capital/<strategy>/capital_<symbol>.png` | 每个策略 × 品种的本金／权益曲线 |
| `capital/symbol_core_overview_<prefix>.xlsx` | 每个策略 × 品种在整个回测期的核心概览指标 |
| `performance/performance_report_<prefix>.xlsx` | 绩效报告 |
| `evaluation/evaluation_report_<prefix>.xlsx` | 深度评价 |

## 目录结构

```
strategy/
├── framework/        ★ 契约层：Strategy / Bar / Signal / Order / Fill / DataPool
├── core/               回测引擎：data_pool / matcher / portfolio_adapter / engine / accounting
├── data_sources/       可插拔 MinuteBarSource：hdf5_index / live_archive
├── strategies/
│   ├── __init__.py     策略自动发现入口
│   ├── 01_double_ma/   69 个已适配单品种策略之一
│   └── ...             其他策略与参考策略
├── performance/        回测后绩效报表 + 深度评价
├── config/             6 份 yaml：strategies/capital/universe/date_range/output/data_source
├── data/               future_list.csv / industry_map.csv
├── tools/              compare_runs / diff_signals / check_barrier_evidence
└── run_backtest.py     回测入口

tests/
├── test_core/          撮合 / 撤单 / 引擎单元测试
└── test_framework/     framework 数据类 / client_order_id 测试

data/future_price/      74 个商品指数 HDF5 行情文件（Git LFS）

docs/
├── ARCHITECTURE.md           三层架构与数据流
├── STRATEGY_CONTRACT.md      策略包契约（编写新策略必读）
├── CONFIG_REFERENCE.md       6 份 yaml + CLI 覆盖说明
├── LIVE_DEPLOYMENT.md        实盘 drop-in 部署 SOP
└── PENDING_ORDER_UPGRADE.md  挂单 / 撤单 / client_order_id 设计文档
```

## 核心设计

> 同一份 `framework/` + `strategies/<member>/` 代码，**回测和实盘共用**。

引擎层 `core/` 仅回测使用；实盘项目自行实现 `LiveDataPool` / `LiveOrderRouter`，
接口签名与 `framework.DataPool` / `core.Matcher` 一致即可。详见
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) 与 [docs/LIVE_DEPLOYMENT.md](docs/LIVE_DEPLOYMENT.md)。

## 编写新策略

最小骨架（参见 `strategy/strategies/jerome/` 的完整实现）：

```python
# strategies/<name>/strategy.py
from framework import Strategy as BaseStrategy, Signal, ORDER_LIMIT, OFFSET_OPEN, SIGNAL_ENTRY

class Strategy(BaseStrategy):
    REQUIRED_UNIVERSE = "self"
    SESSION_NAMES = ["早盘"]
    SUPPORTS_BATCH_PREBUILD = False   # 用了 cancel_order 必须设为 False

    def on_bar(self, bar, snapshot):
        cid = self.new_client_order_id("OL")   # 框架统一分配，符合 CTP OrderRef 约束
        return [Signal(
            symbol=bar.symbol,
            action_datetime=bar.timestamp,
            bar_datetime=bar.timestamp,
            signal_kind=SIGNAL_ENTRY,
            direction=+1,
            offset=OFFSET_OPEN,
            order_type=ORDER_LIMIT,
            session="早盘",
            price=bar.close - 5.0,
            volume_hint=1,
            client_order_id=cid,
        )]

    def on_fill(self, fill):
        super().on_fill(fill)   # 必须，自动维护 self.position
        # 业务清理 …
```

完整契约见 [docs/STRATEGY_CONTRACT.md](docs/STRATEGY_CONTRACT.md)。

### 注册策略并配置参数

新策略至少需要 `strategy/strategies/<name>/strategy.py` 和 `__init__.py`。
`strategy.py` 定义继承 `framework.Strategy` 的 `Strategy` 类；在同目录的
`__init__.py` 中导出它，框架才能按目录名加载：

```python
from .strategy import Strategy

__all__ = ["Strategy"]
```

当前 `strategy/config/strategies.yaml` 只启用了 `ma5ma10`，内容如下：

```yaml
strategies:
  - package: ma5ma10
    enabled: true
    params:
      # 简单移动平均线周期，单位：完整交易日
      fast_period: 5
      slow_period: 10
```

新增策略时，在**现有 `strategies:` 列表末尾**追加一项，不要再写第二个
`strategies:`。`package` 必须与 `<name>` 目录名完全一致，例如：

```yaml
  - package: my_strategy   # 对应 strategies/my_strategy/
    enabled: false         # 保持默认回测仍只运行 ma5ma10
    capital: 1000000       # 可选；不填则使用 capital.yaml 的 per_strategy_capital
    params:                # 可选；传给 Strategy(..., params=...)
      lookback: 20
```

策略代码可用 `self.params.get("lookback", 20)` 读取参数。`enabled` 控制未指定
`--strategy` 时是否运行；`--strategy my_strategy` 会单独运行该策略，即使
`enabled: false`。如果希望默认运行新策略，应把新策略改为 `enabled: true`，
并将 `ma5ma10` 改为 `enabled: false`。如果只用命令行运行未登记的策略，框架
会创建临时默认配置，但不会带入上例的 `params` 和单策略 `capital`，因此建议
仍在此文件登记。目前 `ma5ma10` 的日频快速回测仅支持单策略运行；
`--strategy all` 会强制运行列表中的所有策略，与它混跑会报错。

### 按需调整其他配置

以下文件都位于 `strategy/config/`；新建策略后只需修改与本次回测有关的项：

| 文件 | 何时修改 | 常用内容或命令行覆盖 |
| --- | --- | --- |
| `capital.yaml` | 改默认单策略资金或多策略组合规则 | `per_strategy_capital`、`adapter.type`；单策略资金也可写在上述策略条目的 `capital` |
| `universe.yaml` | 限定回测品种 | `items: [RB, MA]`；临时指定用 `--symbols RB MA`。`items: []` 使用可交易品种全集 |
| `date_range.yaml` | 改默认回测区间或预热长度 | `start`、`end`、`warmup_bars`；临时指定用 `--start`、`--end`、`--warmup-bars` |
| `data_source.yaml` | 切换行情来源或修改本机数据路径 | `data_source.type` 和对应的目录；HDF5 可用 `--data-dir` 临时覆盖 |
| `output.yaml` | 改默认输出目录或文件名前缀 | `output.dir`、`output.prefix`；临时指定用 `--out-dir`、`--prefix` |

另有 `strategy/performance/config.yaml`，它只配置绩效报告的无风险利率、
年交易日数及按成交时间划分时段的 `session_rules`。普通新策略**无需**在这里
增加策略名；只有要调整这些报告口径或时段规则时才修改它。

例如，从项目的 `strategy/` 目录运行已登记的新策略：

```powershell
uv run .\run_backtest.py --strategy my_strategy `
    --data-dir 'D:\lyx\jy\tmp\strategy\data' `
    --symbols RB --start 2024-01-01 --end 2024-12-31T23:59:59 `
    --prefix my_strategy
```

完整的配置字段和覆盖规则见 [docs/CONFIG_REFERENCE.md](docs/CONFIG_REFERENCE.md)。

## 配置数据源

`strategy/config/data_source.yaml`：

```yaml
data_source:
  type: hdf5_index    # 或 live_archive

  hdf5_index:
    data_dir: ../data/future_price   # 仓库内置的 74 个 HDF5 文件

  live_archive:
    bar_dir: /path/to/live/minute_bars
    file_pattern: "{symbol}.parquet"
    schema_version: v1
```

yaml的配置文件也可以从命令行覆盖：

```bash
python strategy/run_backtest.py --strategy jerome \
    --data-source hdf5_index \
    --data-dir /path/to/index/h5 \
    --symbols RB --start 2024-01-01 --end 2024-06-30
```
