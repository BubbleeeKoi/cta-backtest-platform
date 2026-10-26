"""
tests/conftest.py  —— pytest 公共配置

把 strategy/ 加入 sys.path，让测试可以直接 ``from strategies.jerome import ...``
/ ``from core import ...``，与生产脚本 ``run_backtest.py`` 的导入语义保持一致。
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STRATEGY_ROOT = _REPO_ROOT / "strategy"

for p in (_STRATEGY_ROOT / "core", _STRATEGY_ROOT):
    sp = str(p)
    if p.is_dir() and sp not in sys.path:
        sys.path.insert(0, sp)
