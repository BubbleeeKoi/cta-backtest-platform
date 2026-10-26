"""Write the per-strategy handover from final validation artifacts."""
from pathlib import Path
import json
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategies import _CATEGORY_GROUPS


def main():
    coverage_path = ROOT/"output"/"source_validation"/"coverage_final.csv"
    coverage = pd.read_csv(coverage_path).fillna("")
    manifest = json.loads((ROOT/"SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    counts = coverage.status.value_counts().to_dict()
    assert coverage.symbol.nunique() == 74
    assert coverage.strategy.nunique() == 69
    assert len(coverage) == 15318
    assert not counts.get("failed", 0)
    engine_prefix = "source_engine_66_all74_final_v2"
    engine_trades = len(pd.read_csv(ROOT/"output"/"source_validation"/"trades"/f"trades_{engine_prefix}.csv"))
    completion = json.loads((ROOT/"output"/"source_validation"/"runs"/f"{engine_prefix}.complete.json").read_text(encoding="utf-8"))
    assert completion["errors"] == 0 and len(completion["symbols"]) == 74
    text = f'''# 69 个策略逐源文件匹配记录

完成日期：2026-10-26。范围为交接摘要中的趋势、突破、均值回归、量价四类，合计 69 个策略。唯一策略来源为用户指定的桌面 `tqsdk-strategies-main/strategies`；桌面原文件未修改。

## 实现与验证口径

每个策略现在包含独立 `_source.py`。指标函数、常量、原始条件、条件顺序、持仓计数、前值和其他局部状态从对应源文件保留；`strategy.py` 仅承担本地 Strategy 入口。生成工具只转换接口、更新等待和日志，不以通用 MA／通道／因子信号替代不同策略。18 个后期因子策略保留各自源文件的特征函数、权重和分数阈值。

- 原文件与生成文件 SHA-256： [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。每个原文件都能重新生成并逐字校验，而不是仅凭策略名称判断匹配。
- 统一在完成 K 线后计算，15m／1h 完整分钟桶在最后一分钟发布，信号由平台下一可用 bar 撮合。日线全日 OHLCV 在收盘事件发布，下一执行事件成交，不在下一天读取前一天信号后再倒用当日开盘价。
- 日线使用 `tradingday` 合并夜盘；日线全量 OHLCV 替换执行行，成交量不重复累加。没有 09:05 行情的金融期货使用实际首个日盘分钟作为执行事件。
- 单周期策略随 `timeframe` 切换；23／24 保留独立日线参考，切换交易周期；25 保留原始日线、小时线过滤，切换入场周期；04 保留四日日线范围，按选定完成周期的收盘价检查。
- 常规策略目标方向按交接要求固定手数，默认 1 手，不使用源文件资金比例／分数放大仓位。12 网格保留原始多层状态、每层默认 1 手及总上限。`long / short / both` 由本地执行层过滤。
- 原文件中的严格突破、自含当前极值或其他可能不触发的条件照原代码保留；不根据名称或介绍擅自优化为另一种策略。日内时间窗口策略在日线周期可能没有信号。
- 按原始订阅窗口预热；可从回测开始前的本地数据填充，但不读取开始之后的数据或虚构前置成交。缺少完整窗口时等待，不伪造历史数据。

这是本地源文件公式／分支保留与离线完成 K 线验证；没有联网运行天勤 SDK，也不是两套撮合器的逐 tick、逐笔成交一致性结论。SDK 接口形式的兼容计算集中在 `_source_compat.py`；标准差、交叉、EMA／SMA、ATR、RSI 和 BOLL 公式另核对了官方 [tafunc.py](https://raw.githubusercontent.com/shinnytech/tqsdk-python/master/tqsdk/tafunc.py) 与 [ta.py](https://raw.githubusercontent.com/shinnytech/tqsdk-python/master/tqsdk/ta.py)。其中标准差按 SDK 的样本标准差，ATR 保留首个 TR 的 NaN 口径。

## 明确记录的兼容处理

1. 12 网格：原文件函数内赋值模块级 `last_price` 缺少 `global`，补声明；模块状态为每个策略／品种单独创建，避免多个品种串状态。
2. 18 VWAP：成交量窗口总和为零时返回未就绪，跳过该次新计算，保留目标；正常非零窗口的公式和阈值不变。ZC 真实数据检出了这个边界。
3. 19 云图：原函数向滚动 extrema 接口传入切片列表并消费标量，兼容为对应窗口极值。
4. 28 波动突破：原 ADX helper 将 ATR 序列同时当作标量使用，统一读取最后一个 ATR 值；原始突破条件保留。
5. MA／ATR／RSI 的 Series、DataFrame 输入及 BOLL 多套列名在兼容层统一；原始自定义指标函数仍保留在各自程序内。
6. 时间解码按 H5 的上海本地墙钟处理，避免执行主机时区导致时间窗口变化。13 ORB 的原始顶层分钟进位逻辑已保留，并在覆盖参数后重算。

## 验证结果

- 策略和平台测试：326 项通过，覆盖 69 个程序来源、三个周期、真实非空窗口执行、原文件重新生成校验、夜盘、日线成交量、最后一分钟发布、前日枢轴参考、预热因果性、零成交量、SDK 指标参考值和原平台撮合等。
- 真实历史窗口覆盖：69 × 74 × 3 = **15,318** 个组合；**{counts.get('passed',0):,}** 个正常执行，**{counts.get('insufficient_history',0)}** 个缺少完整原始历史窗口，**0** 个执行错误。明细：[coverage_final.csv](output/source_validation/coverage_final.csv)，摘要：[coverage_final.json](output/source_validation/coverage_final.json)。每个组合从空仓和原始窗口启动，验证末尾三次更新；这不是全历史绩效回测。
- 平台成交与报告验证：66 个策略 × 全部 74 品种，2025-12-29 至 2025-12-31，日线，退出码 0、{engine_trades} 笔已平交易。明细在 `output/source_validation/`，前缀 `{engine_prefix}`，并有成功标记。
- 其余 04／13／25：RB、IF 分钟数据，15m，2025-12-24 至 2025-12-31，退出码 0、22 笔已平交易，前缀 `source_engine_intraday_3`。它们在全部 74 品种的三个周期另有上面的规则窗口覆盖。
- 零交易策略也能正常输出日净值、资本 CSV、品种概览及成功标记；不强造交易或空的绩效结论。

## 全部数据与运行

`cta/data/future_price` 共有 74 个 H5 文件、约 3 GB。74 个都有元数据。默认研究回测纳入所有文件，不再按当前 `trade=True` 排除 16 个历史品种。日期默认 2016-01-01 至 2025-12-31，结束日包含全天。具体合约／展期层不属于本轮范围。

```powershell
# 在 cta/strategy 下运行；Python 使用已有 Anaconda 环境
D:/anaconda3/python.exe run_backtest.py --strategy 07_kdj_signal --timeframe 1h --direction both --symbols RB IF --no-plots

# 先生成全部 69 策略 × 74 品种 × 三个周期的任务清单
D:/anaconda3/python.exe batch_single_product_backtest.py --timeframes 15m 1h 1d --directions both --plan-only

# 全历史批量回测：每个任务纳入全部 74 品种，可中断后续跑
D:/anaconda3/python.exe batch_single_product_backtest.py --timeframes 15m 1h 1d --directions both

# 从桌面原文件重新核验生成结果，不改原文件
D:/anaconda3/python.exe tools/sync_source_programs.py "C:/Users/Administrator/Desktop/ChenLiyuan/期货量化/tqsdk-strategies-main/strategies" --check
```

全品种批量输出前缀为 `<策略名>_<方向>_<周期>_all`；代码、配置和数据版本保存在元数据中，仅在成功标记的批次指纹一致时跳过。原来的回测输出继续保留，不当作新规则的结果。批量默认关闭逐品种 PNG，CSV 和报告保留；需要图片可加 `--plots`。首次全历史、多周期批量计算量较大；本次没有声称已完成全部十年绩效任务。

`params.py` 中 `TIMEFRAME / DIRECTION / VOLUME` 生效；指标参数按原始名称写入 `SOURCE_PARAMS`。旧通用 `FAST_PERIOD / SLOW_PERIOD / SIGNAL_PERIOD` 不驱动源程序。示例：03 的 `SOURCE_PARAMS = {{"RSI_PERIOD": 14}}`。31 个组合／对冲策略未纳入本轮。

## 逐个对应清单

“正常／不足”是 74 品种 × 三个周期的窗口覆盖组合数；每行总计 222。源文件名为对应策略名加 `.py`，入口及哈希可在清单中复核。

| 本地策略（点击查看保留的源规则） | 原始入口 | 正常组合 | 历史不足 | 执行错误 |
| --- | --- | ---: | ---: | ---: |
'''
    names = sorted(set.union(*list(_CATEGORY_GROUPS.values())[:4]))
    for name in names:
        subset = coverage[coverage.strategy == name]
        stats = subset.status.value_counts().to_dict()
        text += (f'| [{name}](strategies/{name}/_source.py) | `{manifest[name]["entry"]}` | '
                 f'{stats.get("passed",0)} | {stats.get("insufficient_history",0)} | {stats.get("failed",0)} |\n')
    (ROOT/"STRATEGY_MATCHING.md").write_text(text, encoding="utf-8", newline="\n")
    print("STRATEGY_MATCHING.md generated: 69 rows")


if __name__ == "__main__":
    main()
