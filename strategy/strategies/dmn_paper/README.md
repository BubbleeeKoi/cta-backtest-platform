# Deep Momentum Network (DMN) paper reproduction

This package implements the Sharpe-optimised LSTM with direct position output
from Lim, Zohren and Roberts, *Enhancing Time-Series Momentum Strategies Using
Deep Neural Networks*. One model is trained across products. The output is in
[-1, 1] and scaled using a 15% annual volatility target and 60-day EWM
volatility estimate. Inputs are five volatility-normalised return horizons
(1, 21, 63, 126, 252 trading days) and three normalised MACD signals
(8/24, 16/48, 32/96). Each sample has a 63-day history. The loss is negative
annualised portfolio Sharpe, optionally with a turnover penalty.

The available Chinese product-index data are not the paper's US/global
ratio-adjusted continuous futures data. This is a method reproduction and a
new-market experiment; its performance numbers cannot match the paper.
Product-index prices are used for signals and fills, so the execution backtest
does not establish that the returns are tradable.

## Install

Use Python 3.10-3.12. From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r strategy\strategies\dmn_paper\requirements-dmn.txt
cd strategy
```

On this machine, if `py -3.11` is unavailable, use
`D:\codex\.uv-python\cpython-3.11.15-windows-x86_64-none\python.exe -m venv .venv`
instead. The base project reports need pandas 2.2 or later because they use
the `ME` monthly frequency. The DMN requirements file ensures that version.

## Use the supplied checkpoints

`models/dmn_paper.pt` is the zero-turnover-penalty checkpoint.
`models/dmn_paper_cost10.pt` was trained with a 10 bp turnover penalty. Both
were trained on all usable products through 2020-12-31, selected using 2021,
and tested only on 2022-2025. The full results and assumptions are in
`output/dmn_paper_results_20260929.md`.

From `strategy/`, evaluate the turnover-regularised checkpoint at an assumed
2 bp one-way trading cost:

```powershell
..\.venv\Scripts\python.exe -m strategies.dmn_paper.evaluate --data-dir 'D:\lyx\jy\tmp\strategy\data' --model models/dmn_paper_cost10.pt --start 2022-01-01 --end 2025-12-31 --cost-bps 2 --out output/dmn_paper_cost10_recheck.csv
```

This theoretical report uses close-to-close returns and the paper's return
formula. It does not simulate fills, futures rolls, or actual exchange fees.

## Retrain

From `strategy/`:

```powershell
..\.venv\Scripts\python.exe -m strategies.dmn_paper.train --data-dir 'D:\lyx\jy\tmp\strategy\data' --train-end 2020-12-31 --valid-end 2021-12-31 --cost-bps 10 --out models/dmn_paper_retrained.pt
```

The trainer uses every `.h5` product file by default. A quick smoke run can
use `--symbols RB AU CU IF --epochs 3`. Defaults are 20 LSTM units, batch size
1024, at most 50 epochs, Adam learning rate 0.001, seed 42, and early stopping
after ten epochs without a better validation Sharpe. Set `--cost-bps 0` to
train the no-cost variant. Never use validation Sharpe as a test result.

## Run the framework order backtest

The ready-to-use `strategy/config_dmn/` selects the supplied 10 bp checkpoint
with 10 million capital per product. It leaves the project's ordinary
`strategy/config/` unchanged. Its `strategies.yaml` entry is:

```yaml
strategies:
  - package: dmn_paper
    enabled: true
    capital: 10000000
    params:
      model_path: D:/lyx/shi_project/cta_backtest_jerome_demo/strategy/models/dmn_paper_cost10.pt
```

Then, from `strategy/`:

```powershell
..\.venv\Scripts\python.exe -m strategies.dmn_paper.backtest --config-dir config_dmn --strategy dmn_paper --adapter passthrough --data-dir 'D:\lyx\jy\tmp\strategy\data' --symbols RB AU CU IF --start 2022-01-01 --end 2025-12-31T23:59:59 --prefix dmn_paper_cost10_recheck
```

The launcher loads PyTorch before the framework's native dependencies, which
avoids a Windows DLL import-order conflict in some environments. The explicit
end-of-day time includes all minute bars on 2025-12-31. A date-only `--end`
would exclude that day's bars in this framework.

The strategy observes a daily close and rebalances at the next trading day's
first minute open. It converts target exposure to whole contract lots using
per-symbol `allocated_capital` and the product `point` multiplier, then
rebalances from its filled position. With the default 1,000,000 capital, IF
may never reach one lot; 10,000,000 enabled IF trades in our four-product test.
The framework's `ORDER_EXACT` fills at supplied index prices, without spread,
slippage, or roll costs. Framework output is therefore different from the
paper-style daily report. You can limit position size with `max_leverage` in
the strategy params; without it, no leverage cap is applied.

You can leave `enabled: false` in the YAML and still select the strategy via
`--strategy dmn_paper`. The checkpoint stores its training and validation
cutoffs; the strategy does not trade through the validation period.
