# data_sources/  ——  回测可插拔数据源

回测端 `BacktestDataPool` 不再写死"从哪里读 minute bar"，而是通过本包提供
的 `MinuteBarSource` 抽象注入具体加载器。

## 现有 source

| type 字符串    | 类                  | 用途                                       |
|----------------|---------------------|--------------------------------------------|
| `hdf5_index`   | `HDF5IndexSource`   | 研究回测：商品指数 HDF5（多合约加权）      |
| `live_archive` | `LiveArchiveSource` | 对账回测：与实盘同源的 minute bar 归档     |

## 切换方式

`strategy/config/data_source.yaml`:

```yaml
data_source:
  type: hdf5_index    # 或 live_archive

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

## 给 IT 的 LiveArchiveSource 接入说明

实盘行情服务每天会推送 minute bar 给我们。我们要做两件事：

1. **每天落盘一份归档**：每根完成的 bar 追加到 `bar_dir/{SYMBOL}.parquet`
   （或 csv / h5；通过 `file_pattern` 配）。
2. **格式严格对齐**：让对账回测能用同一份策略代码、同一份 schema 跑出与
   实盘一致的 signals。

### 统一 schema

DataFrame 返回时必须满足：

| 列 / 索引          | 类型              | 说明                                       |
|--------------------|-------------------|--------------------------------------------|
| index `actiontime` | `DatetimeIndex`   | bar 归属时刻，严格升序、无重复             |
| `open / high / low / close` | `float64` | 量价 4 列                                  |
| `volume`           | `float64`         | 当根 bar 成交量                            |
| `oi`               | `float64`         | 持仓量，缺失填 `0.0`                       |
| `tradingday`       | `datetime64[ns]`  | 交易日；夜盘 bar **必须归属次日交易日**     |

夜盘归属规则与现有商品指数 HDF5 一致（21:00 后的 bar 属于下一交易日），
不要按 `actiontime.normalize()` 简单兜底——否则夜盘 bar 会被错挂到当日。

### 实现入口

`strategy/data_sources/live_archive.py:LiveArchiveSource`

- 默认实现：自动按文件后缀路由到 `read_parquet / read_csv / read_hdf`
- 自定义读取：继承并覆盖 `_load_one_symbol(symbol, path) -> DataFrame`
- 末端 `validate_schema` 兜底补 `oi=0.0`、强制升序、统一 `tradingday` 列类型

### 验证清单

接入后用以下命令做端到端冒烟测试：

```bash
# 1) 切到 live_archive
python strategy/run_backtest.py --strategy jerome --data-source live_archive \
    --symbols RB --start <最近某交易日> --end <同上> --prefix verify_smoke

# 2) 看 signals 落盘
ls strategy/output/signals/signals_verify_smoke.csv

# 3) 与同日实盘 signals 对账
python strategy/tools/diff_signals.py \
    --backtest strategy/output/signals/signals_verify_smoke.csv \
    --live     /path/to/live/signals/signals_YYYYMMDD.csv \
    --report   strategy/output/verify/diff_YYYYMMDD.csv
```

预期：`status` 列绝大多数为 `OK`；少量 `ATTR_MISMATCH` 可通过 `bar_close_bt`
vs `bar_close_live` 列辅助定位。

### 实盘端 SignalRecorder

实盘 runner 在每根 bar 调用 `strategy.on_bar()` 收到 signals 后：

```python
from framework import SignalRecorder

recorder = SignalRecorder()  # 启动时
# 每根 bar:
for sig in signals:
    recorder.record(sig, current_bar)
# 日终:
recorder.save(Path(f"live_output/signals/signals_{trading_date}.csv"))
```

落盘 CSV 与回测端 schema 完全一致，可直接喂给 `diff_signals.py`。

## 新增 source

1. 写一个 `MinuteBarSource` 子类，实现 `load(symbol)` + `list_available_symbols()`
2. 在 `registry.py` 的 `_BUILDERS` 里注册（或运行时 `register_source(...)`）
3. 在 `config/data_source.yaml` 的对应 type 块下提供参数
