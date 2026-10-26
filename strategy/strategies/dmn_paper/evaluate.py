"""Evaluate the paper's daily close-to-close portfolio return definition.

This research report is distinct from the framework's next-open order backtest.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources.hdf5_index import HDF5IndexSource

from .model import (
    FEATURE_NAMES, LOOKBACK, daily_features, default_model_path, load_network,
    valid_sample_days,
)


def main() -> int:
    import torch

    parser = argparse.ArgumentParser(description="Evaluate daily DMN portfolio returns")
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=default_model_path())
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--start", default=None, help="first realized-return date")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--cost-bps", type=float, default=0.0)
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).resolve().parents[2] / "output" / "dmn_paper_daily.csv")
    args = parser.parse_args()
    if args.cost_bps < 0:
        raise ValueError("cost-bps must be nonnegative")
    model, metadata = load_network(str(args.model.resolve()))
    if int(metadata["lookback"]) != LOOKBACK:
        raise ValueError("model lookback differs from evaluator code")
    start = pd.Timestamp(args.start or metadata["valid_end"]) + pd.Timedelta(days=1)
    end = pd.Timestamp(args.end)
    source = HDF5IndexSource(str(args.data_dir))
    symbols = args.symbols or metadata["symbols"]
    records = []
    for symbol in symbols:
        bars = source.load(symbol)
        if bars is None or bars.empty:
            print(f"skip {symbol}: no minute bars")
            continue
        frame = daily_features(bars)
        del bars
        values = frame.loc[:, list(FEATURE_NAMES)].to_numpy(dtype=np.float32)
        positions = valid_sample_days(frame)
        if not positions:
            continue
        predictions = []
        with torch.no_grad():
            for offset in range(0, len(positions), 512):
                block = positions[offset:offset + 512]
                windows = np.stack([values[i - LOOKBACK + 1:i + 1] for i in block])
                predictions.extend(model(torch.from_numpy(windows)).numpy().tolist())
        previous_exposure = 0.0
        for i, prediction in zip(positions, predictions):
            row = frame.iloc[i]
            exposure = float(prediction) * float(metadata["target_vol"]) / float(row["sigma_ann"])
            day = pd.Timestamp(row["next_day"])
            if start <= day <= end:
                gross = exposure * float(row["next_return"])
                turnover = abs(exposure - previous_exposure)
                records.append((day, symbol, exposure, gross, turnover))
                previous_exposure = exposure
    if not records:
        raise ValueError("no out-of-sample predictions in selected range")
    detail = pd.DataFrame(records, columns=["date", "symbol", "exposure", "gross_return", "turnover"])
    detail["net_return"] = detail["gross_return"] - args.cost_bps / 10_000.0 * detail["turnover"]
    daily = detail.groupby("date", sort=True).agg(
        return_gross=("gross_return", "mean"),
        return_net=("net_return", "mean"),
        mean_turnover=("turnover", "mean"),
        n_assets=("symbol", "size"),
    )
    daily["equity_net"] = (1.0 + daily["return_net"]).cumprod()
    volatility = daily["return_net"].std(ddof=0)
    sharpe = float(daily["return_net"].mean() / volatility * np.sqrt(252)) if volatility > 0 else float("nan")
    drawdown = (daily["equity_net"] / daily["equity_net"].cummax() - 1.0).min()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    daily.to_csv(args.out, float_format="%.10g")
    print(f"saved {args.out}; days={len(daily)}; Sharpe={sharpe:.3f}; "
          f"max_drawdown={drawdown:.2%}; final_equity={daily['equity_net'].iloc[-1]:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
