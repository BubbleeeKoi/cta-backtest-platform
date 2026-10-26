"""Exercise every migrated rule against real trailing HDF5 windows.

This is data/rule coverage validation, not a historical performance report.
Each rule starts flat with its original serial length and runs three updates.
"""
from __future__ import annotations
import argparse
from collections import deque
import json
from pathlib import Path
import sys
import traceback
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data_sources import HDF5IndexSource
from strategies import _CATEGORY_GROUPS, load_strategy_class


def aggregate(frame, seconds):
    keys = (frame.tradingday.dt.normalize() if seconds == 86400 else
            frame.index.floor(f"{seconds}s"))
    frame = frame.assign(_key=np.asarray(keys), _end=frame.index)
    grouped = frame.groupby("_key", sort=True).agg(
        open=("open", "first"), high=("high", "max"), low=("low", "min"),
        close=("close", "last"), volume=("volume", "sum"), oi=("oi", "last"),
        completed_at=("_end", "max"))
    grouped["timestamp"] = grouped.index
    # The final bucket has not been closed by a subsequent input event yet.
    return grouped.iloc[:-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT.parent/"data"/"future_price")
    parser.add_argument("--output", type=Path, default=ROOT/"output"/"source_validation"/"coverage.csv")
    parser.add_argument("--symbols", nargs="+")
    parser.add_argument("--timeframes", nargs="+", default=["15m", "1h", "1d"])
    parser.add_argument("--strategies", nargs="+", default=None)
    args = parser.parse_args()
    source = HDF5IndexSource(str(args.data_dir))
    symbols = args.symbols or source.list_available_symbols()
    names = sorted(set.union(*list(_CATEGORY_GROUPS.values())[:4]))
    if args.strategies:
        assert set(args.strategies) <= set(names)
        names = sorted(args.strategies)
    results = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for index, symbol in enumerate(symbols, 1):
        minute = source.load(symbol)
        if minute is None or minute.empty:
            raise ValueError(f"No readable data: {symbol}")
        cache = {}
        for timeframe in args.timeframes:
            entry_seconds = {"15m": 900, "1h": 3600, "1d": 86400}[timeframe]
            if entry_seconds not in cache:
                cache[entry_seconds] = aggregate(minute, entry_seconds)
            events = cache[entry_seconds].tail(3)
            for name in names:
                record = dict(symbol=symbol, strategy=name, timeframe=timeframe,
                              status="passed", updates=0, nonzero_targets=0, error="")
                try:
                    strategy = load_strategy_class(name)(name, {"symbol": symbol}, None,
                                                        dict(timeframe=timeframe, direction="both"))
                    for _, event in events.iterrows():
                        strategy._api.changed.clear()
                        strategy._api.changed_stamps.clear()
                        ready = True
                        last_rows = []
                        for stream in strategy._streams:
                            seconds = stream["duration"]
                            if seconds not in cache:
                                cache[seconds] = aggregate(minute, seconds)
                            data = cache[seconds]
                            end = data.completed_at.searchsorted(event.completed_at, side="right")
                            needed = stream["length"]-int(stream["previous"])
                            sample = data.iloc[max(0, end-needed):end]
                            if len(sample) < needed:
                                ready = False
                                break
                            last_stamp = sample.timestamp.iloc[-1]
                            previous_stamp = stream.get("validated_stamp")
                            values = sample.drop(columns="completed_at").to_dict("records")
                            stream["history"].clear()
                            stream["history"].extend(values[:-1])
                            strategy._update_frame(stream, values[-1])
                            if previous_stamp != last_stamp:
                                strategy._api.changed.add(id(stream["frame"]))
                                strategy._api.changed_stamps.add(stream["frame"].iloc[-1]["datetime"])
                            stream["validated_stamp"] = last_stamp
                        if not ready:
                            record["status"] = "insufficient_history"
                            continue
                        strategy._day_open = event.open
                        with np.errstate(divide="ignore", invalid="ignore"):
                            target = strategy._decision(event.to_dict())
                        record["updates"] += 1
                        if target is not None:
                            record["nonzero_targets"] += int(target != 0)
                            strategy.position.long_volume = max(target, 0)
                            strategy.position.short_volume = max(-target, 0)
                except Exception as exc:
                    record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                results.append(record)
        pd.DataFrame(results).to_csv(args.output, index=False, encoding="utf-8-sig")
        print(f"[{index}/{len(symbols)}] {symbol}: {len(results)} combinations, "
              f"failures={sum(r['status']=='failed' for r in results)}", flush=True)
        del minute, cache
    counts = pd.DataFrame(results).status.value_counts().to_dict()
    summary = dict(symbols=len(symbols), strategies=len(names), timeframes=args.timeframes,
                   combinations=len(results), counts=counts,
                   note="Trailing-window execution coverage; not full-history PnL backtests")
    args.output.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return int(counts.get("failed", 0) != 0)


if __name__ == "__main__":
    raise SystemExit(main())
