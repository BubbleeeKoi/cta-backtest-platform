"""Train a shared Sharpe-optimised Deep Momentum Network.

Run from the project's ``strategy`` directory with
``python -m strategies.dmn_paper.train --data-dir ...``.
"""

from __future__ import annotations

import argparse
import copy
import random
from pathlib import Path

import numpy as np
import pandas as pd

from data_sources.hdf5_index import HDF5IndexSource

from .model import (
    FEATURE_NAMES, LOOKBACK, TARGET_VOL, daily_features, default_model_path,
    make_network,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the paper's daily Sharpe-optimised LSTM")
    parser.add_argument("--data-dir", type=Path, required=True, help="directory of {SYMBOL}.h5 files")
    parser.add_argument("--symbols", nargs="*", help="default: every HDF5 file in data-dir")
    parser.add_argument("--train-end", default="2020-12-31")
    parser.add_argument("--valid-end", default="2021-12-31")
    parser.add_argument("--out", type=Path, default=default_model_path())
    parser.add_argument("--hidden-size", type=int, default=20)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=1024)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--cost-bps", type=float, default=0.0,
                        help="optional turnover penalty per unit exposure change")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    return parser.parse_args()


def load_panel(source: HDF5IndexSource, symbols: list[str]) -> dict[str, pd.DataFrame]:
    panel = {}
    for symbol in symbols:
        bars = source.load(symbol)
        if bars is None or bars.empty:
            print(f"skip {symbol}: no minute bars")
            continue
        features = daily_features(bars)
        del bars
        if len(features) < 400:
            print(f"skip {symbol}: only {len(features)} trading days")
            continue
        panel[symbol] = features
        print(f"loaded {symbol}: {len(features)} days ({features.index.min().date()}–"
              f"{features.index.max().date()})")
    return panel


class Samples:
    """Lazy cross-asset 63-day sequences, selected by the *label* date."""

    def __init__(self, panel: dict[str, pd.DataFrame], after: pd.Timestamp | None,
                 through: pd.Timestamp, target_vol: float):
        self.items = []
        self.arrays = {}
        for symbol, df in panel.items():
            values = df.loc[:, list(FEATURE_NAMES)].to_numpy(dtype=np.float32)
            sigma = df["sigma_ann"].to_numpy(dtype=np.float32)
            nxt = df["next_return"].to_numpy(dtype=np.float32)
            days = pd.DatetimeIndex(df["next_day"])
            clean = np.isfinite(values).all(axis=1) & np.isfinite(sigma) & (sigma > 0)
            self.arrays[symbol] = (values, sigma, nxt, days)
            for i in range(LOOKBACK, len(df) - 1):
                label_day = days[i]
                if pd.isna(label_day) or label_day > through or (after is not None and label_day <= after):
                    continue
                if not clean[i - LOOKBACK:i + 1].all() or not np.isfinite(nxt[i]):
                    continue
                self.items.append((symbol, i))
        self.target_vol = target_vol

    def __len__(self):
        return len(self.items)

    def __getitem__(self, n):
        symbol, i = self.items[n]
        values, sigma, nxt, _ = self.arrays[symbol]
        return (
            values[i - LOOKBACK + 1:i + 1],
            values[i - LOOKBACK:i],
            np.float32(nxt[i] * self.target_vol / sigma[i]),
            np.float32(self.target_vol / sigma[i]),
            np.float32(self.target_vol / sigma[i - 1]),
        )


def strategy_returns(model, batch, cost_rate: float, device: str):
    import torch

    x, x_previous, scaled_next_return, exposure, previous_exposure = (
        value.to(device) for value in batch
    )
    prediction = model(x)
    realized = prediction * scaled_next_return
    if cost_rate:
        previous_prediction = model(x_previous)
        turnover = torch.abs(prediction * exposure - previous_prediction * previous_exposure)
        realized = realized - cost_rate * turnover
    return realized


def sharpe_loss(returns):
    import torch

    return -torch.sqrt(torch.tensor(252.0, device=returns.device)) * returns.mean() / (
        returns.std(unbiased=False) + 1e-6
    )


def validate(model, loader, cost_rate: float, device: str) -> float:
    import torch

    model.eval()
    chunks = []
    with torch.no_grad():
        for batch in loader:
            chunks.append(strategy_returns(model, batch, cost_rate, device).cpu())
    returns = torch.cat(chunks)
    return float(-sharpe_loss(returns))


def main() -> int:
    import torch
    from torch.utils.data import DataLoader

    args = parse_args()
    if args.hidden_size <= 0 or args.epochs <= 0 or args.batch_size < 2:
        raise ValueError("hidden-size/epochs must be positive and batch-size must be >= 2")
    if args.cost_bps < 0:
        raise ValueError("cost-bps must be nonnegative")
    train_end = pd.Timestamp(args.train_end).normalize()
    valid_end = pd.Timestamp(args.valid_end).normalize()
    if valid_end <= train_end:
        raise ValueError("valid-end must be later than train-end")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    source = HDF5IndexSource(str(args.data_dir))
    symbols = args.symbols or source.list_available_symbols()
    if not symbols:
        raise ValueError(f"no .h5 files found in {args.data_dir}")
    panel = load_panel(source, symbols)
    training = Samples(panel, None, train_end, TARGET_VOL)
    validation = Samples(panel, train_end, valid_end, TARGET_VOL)
    print(f"train samples: {len(training):,}; validation samples: {len(validation):,}")
    if len(training) < args.batch_size or len(validation) < 100:
        raise ValueError("insufficient samples; choose older symbols or later split dates")
    train_loader = DataLoader(training, batch_size=args.batch_size, shuffle=True, num_workers=0)
    valid_loader = DataLoader(validation, batch_size=args.batch_size, shuffle=False, num_workers=0)
    model = make_network(hidden_size=args.hidden_size).to(args.device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    cost_rate = args.cost_bps / 10_000.0
    best_sharpe = -float("inf")
    best_state = None
    stale = 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        losses = []
        for batch in train_loader:
            optimizer.zero_grad()
            realized = strategy_returns(model, batch, cost_rate, args.device)
            loss = sharpe_loss(realized)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            losses.append(float(loss.detach()))
        score = validate(model, valid_loader, cost_rate, args.device)
        print(f"epoch {epoch:03d} train_loss={np.mean(losses):.4f} valid_sharpe={score:.4f}")
        if score > best_sharpe + 1e-4:
            best_sharpe = score
            best_state = copy.deepcopy({key: value.detach().cpu() for key, value in model.state_dict().items()})
            stale = 0
        else:
            stale += 1
            if stale >= args.patience:
                print("early stop")
                break
    if best_state is None:
        raise RuntimeError("training did not produce a valid checkpoint")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": best_state,
        "hidden_size": args.hidden_size,
        "feature_names": FEATURE_NAMES,
        "lookback": LOOKBACK,
        "target_vol": TARGET_VOL,
        "train_end": str(train_end.date()),
        "valid_end": str(valid_end.date()),
        "cost_bps": args.cost_bps,
        "symbols": sorted(panel),
        "best_validation_sharpe": best_sharpe,
    }, args.out)
    print(f"saved {args.out} (validation Sharpe={best_sharpe:.4f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
