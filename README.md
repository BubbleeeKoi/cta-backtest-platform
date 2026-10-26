# CTA 批量回测平台

本项目包含 69 个已适配策略和 74 个商品指数 HDF5 行情文件，可直接运行全品种批量回测。行情文件使用 Git LFS 管理。

## 1. 下载项目

```powershell
git lfs install
git clone https://github.com/BubbleeeKoi/cta-backtest-platform.git
cd cta-backtest-platform
git lfs pull
```

确认 `data/future_price/` 中存在 74 个 `.h5` 文件。

## 2. 安装依赖

```powershell
D:\anaconda3\python.exe -m pip install -r requirements.txt
```

## 3. 运行全部日线回测

```powershell
cd strategy
D:\anaconda3\python.exe -u batch_single_product_backtest.py --directions both --timeframes 1d --plots
```

该命令运行：

- 前四类共 69 个策略
- `both`：多空双向
- `1d`：日线
- 全部 74 个品种
- `--plots`：生成逐策略、逐品种的权益曲线 PNG

默认回测日期在 `strategy/config/date_range.yaml` 中设置。任务按策略依次运行；中断后再次执行相同命令，会跳过同一批次中已经成功完成的任务。

## 4. 查看结果

全部结果位于：

```text
strategy/output/
```

主要目录：

| 路径 | 内容 |
| --- | --- |
| `strategy/output/trades/` | 成交流水 CSV |
| `strategy/output/signals/` | 策略信号 CSV |
| `strategy/output/actions/` | 下单、撤单和成交动作 CSV |
| `strategy/output/daily/symbol/` | 各品种每日盈亏 CSV |
| `strategy/output/daily/portfolio/` | 组合每日盈亏 CSV |
| `strategy/output/capital/` | 每日权益 CSV、品种概览和 PNG 权益曲线 |
| `strategy/output/performance/` | 绩效报告 XLSX |
| `strategy/output/evaluation/` | 深度评价报告 XLSX |
| `strategy/output/runs/` | 运行参数、状态和完成标记 JSON |
| `strategy/output/batch_logs/` | 批量任务及单策略运行日志 |

日线结果的文件前缀格式为：

```text
<策略名>_both_1d_all
```

例如 `01_double_ma` 的主要结果：

```text
strategy/output/trades/trades_01_double_ma_both_1d_all.csv
strategy/output/performance/performance_report_01_double_ma_both_1d_all.xlsx
strategy/output/evaluation/evaluation_report_01_double_ma_both_1d_all.xlsx
```

PNG 权益曲线位于：

```text
strategy/output/capital/<回测前缀>/<策略名>/capital_<品种>.png
```

例如：

```text
strategy/output/capital/01_double_ma_both_1d_all/01_double_ma/capital_RB.png
```

运行中的总体进度和每个策略的详细日志位于：

```text
strategy/output/batch_logs/
```
