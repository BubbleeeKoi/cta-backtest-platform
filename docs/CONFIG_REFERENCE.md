# 配置参考

`strategy/config/` 下 6 个 yaml 文件，**正交**关注点：

| 文件 | 关注点 | 典型 CLI 覆盖 |
| --- | --- | --- |
| `strategies.yaml` | 哪些策略包参与 | `--strategy jerome` / `--strategy all` |
| `capital.yaml` | 资金分配 + adapter 规则 | `--adapter capped_capital` |
| `universe.yaml` | 品种 / 合约清单 | `--symbols RB MA CU` / `--level contract` |
| `date_range.yaml` | 回测时段 + 预热长度 | `--start ... --end ...` / `--warmup-bars 1000` |
| `output.yaml` | 输出目录 + 前缀 | `--out-dir ... --prefix ...` |
| `data_source.yaml` | 行情数据源选择 + 路径 | `--data-source ...` / `--data-dir ...` |

## strategies.yaml

```yaml
strategies:
  - package: jerome
    enabled: true       # false 则本次跳过
  # - package: <other>
  #   enabled: true
```

CLI:
```bash
--strategy jerome             # 只跑这一个，其它全跳过
--strategy jerome other       # 跑指定的子集
--strategy all                # 全部 enabled=true
```

## capital.yaml

```yaml
per_strategy_capital: 1_000_000

adapter:
  type: passthrough           # passthrough | capped_capital | conflict_dedup

  # capped_capital 专用
  per_symbol_capital_cap: 3_000_000
  total_capital: 30_000_000

  # conflict_dedup 专用
  on_conflict: dedup_signed   # dedup_signed | stack | first_wins
```

### 三种 adapter

| Adapter | 何时用 |
| --- | --- |
| `passthrough` | 多策略独立跑，无组合层干涉。每个 strategy × symbol 仓位独立。 |
| `capped_capital` | 多策略组合：限制每品种跨策略总名义市值，避免某品种过度集中 |
| `conflict_dedup` | 多策略组合：同时段同品种反向信号互相抵消（`dedup_signed`） |

## universe.yaml

```yaml
level: product                # product | contract
items: []                     # 空 = future_list.csv 中 trade=True 全集
```

CLI:
```bash
--symbols RB MA CU            # 锁定品种
--level contract              # 切到合约级
```

## date_range.yaml

```yaml
date_range:
  start: ""
  end:   ""
  warmup_bars: 500            # on_init 预热段长度
```

## output.yaml

```yaml
output:
  dir:    output
  prefix: ""                  # 留空则按策略名 / adapter 自动推导
```

输出文件命名规则：
```
output/
├── trades/trades_<prefix>.csv
├── daily/symbol/daily_pnl_<prefix>.csv
└── daily/portfolio/daily_pnl_portfolio_<prefix>.csv
```

## data_source.yaml

回测端 ``BacktestDataPool`` 通过 ``MinuteBarSource`` 抽象注入具体加载器，
当前支持 ``hdf5_index``（研究回测：商品指数 HDF5）与 ``live_archive``
（对账回测：与实盘同源的 minute bar 归档）两种。

```yaml
data_source:
  type: hdf5_index        # 或 live_archive

  hdf5_index:
    data_dir: /path/to/index/h5

  live_archive:
    bar_dir: /path/to/live/minute_bars
    file_pattern: "{symbol}.parquet"
    schema_version: v1
```

CLI 临时覆盖：

```bash
python strategy/run_backtest.py --data-source live_archive --strategy jerome ...
```

**此文件机器相关**，建议每台机器维护本地副本，不入 git（可在 `.gitignore` 排除 + 提供 `data_source.template.yaml` 入版本控制）。

新增 source 的接入说明见 [`strategy/data_sources/README.md`](../strategy/data_sources/README.md)。
