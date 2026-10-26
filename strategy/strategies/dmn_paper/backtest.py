"""Launch the repository backtest with PyTorch native libraries loaded first."""

from __future__ import annotations

import torch  # noqa: F401


def main() -> int:
    from run_backtest import main as run_main

    return run_main()


if __name__ == "__main__":
    raise SystemExit(main())
