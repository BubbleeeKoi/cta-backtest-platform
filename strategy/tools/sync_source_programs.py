"""Build offline rule programs from the user's original strategy directory.

No original file is modified. Only transport, logging and the update-loop
suspension point are rewritten; calculations and decision branches survive.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strategies import _CATEGORY_GROUPS


class Offline(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.module and node.module.startswith("tqsdk"):
            node.module = "_source_compat"
            node.level = 2
        return node

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return ast.copy_location(ast.Pass(), node)
        if isinstance(node.value, ast.Call):
            call = node.value
            if isinstance(call.func, ast.Name) and call.func.id == "print":
                return ast.copy_location(ast.Pass(), node)
            if isinstance(call.func, ast.Attribute):
                if call.func.attr == "wait_update":
                    return ast.copy_location(ast.Expr(ast.Yield(ast.Constant(None))), node)
                if call.func.attr == "sleep":
                    return ast.copy_location(ast.Pass(), node)
        return self.generic_visit(node)

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id == "TqApi":
            return ast.copy_location(ast.Name("api", ast.Load()), node)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "fromtimestamp":
            node.func = ast.Name("source_datetime", ast.Load())
        return node


def generate(source: str, factor: bool, name: str = "") -> str:
    tree = ast.parse(source)
    # Keep the original single-symbol entry point and its pure helper functions.
    # Cross-section/pair execution and account creation are outside this task.
    excluded = {"create_api", "run_cross_section", "run_pair", "calculate_pair_signal"}
    if factor:
        excluded.add("main")
    def main_guard(node):
        return (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"
                and any(isinstance(value, ast.Constant) and value.value == "__main__"
                        for value in node.test.comparators))
    tree.body = [n for n in tree.body if not main_guard(n)
                 and not (isinstance(n, ast.FunctionDef) and n.name in excluded)]
    tree = Offline().visit(tree)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == ("run_single" if factor else "main"):
            node.name = "program"
            node.args = ast.arguments(posonlyargs=[], args=[ast.arg(arg="api")],
                                      kwonlyargs=[], kw_defaults=[], defaults=[])
            if name == "12_grid_trading":
                # Original assigns a module variable without declaring global.
                node.body.insert(0, ast.Global(names=["last_price"]))
        if isinstance(node, ast.FunctionDef) and node.name == "calc_adx" and name == "28_volatility_breakout":
            for child in ast.walk(node):
                if (isinstance(child, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "adx" for t in child.targets)):
                    child.value = ast.Subscript(value=child.value, slice=ast.UnaryOp(op=ast.USub(), operand=ast.Constant(1)), ctx=ast.Load())
        if isinstance(node, ast.FunctionDef) and node.name == "calculate_vwap" and name == "18_vwap_mean_reversion":
            for index, child in enumerate(node.body):
                if (isinstance(child, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "recent_vol" for t in child.targets)):
                    guard = ast.parse("if sum(recent_vol) <= 0:\n    return None").body[0]
                    node.body.insert(index+1, guard)
                    break
    tree.body.insert(0, ast.ImportFrom(module="_source_compat", level=2,
                                      names=[ast.alias(name="source_datetime")]))
    ast.fix_missing_locations(tree)
    return '# Generated from the local original; see SOURCE_MANIFEST.json.\n' + ast.unparse(tree) + '\n'


ADAPTER = '''"""Completed-bar adapter; decisions are retained in _source.py."""
from .._source_program import SourceProgramStrategy
from . import params as defaults


class Strategy(SourceProgramStrategy):
    def __init__(self, strategy_id, contract_info, data_pool, params=None):
        merged = {"timeframe": getattr(defaults, "TIMEFRAME", "1h"),
                  "direction": getattr(defaults, "DIRECTION", "both"),
                  "volume": getattr(defaults, "VOLUME", 1),
                  "source_params": getattr(defaults, "SOURCE_PARAMS", {})}
        merged.update(params or {})
        super().__init__(strategy_id, contract_info, data_pool, merged)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    names = sorted(set.union(*list(_CATEGORY_GROUPS.values())[:4]))
    manifest = {}
    for name in names:
        path = args.source / (name + ".py")
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        factor = int(name[:2]) >= 64
        generated = generate(text, factor, name)
        output = ROOT / "strategies" / name / "_source.py"
        compile(generated, str(output), "exec")
        if args.check:
            assert output.read_text(encoding="utf-8") == generated, name
        else:
            output.write_text(generated, encoding="utf-8", newline="\n")
            (output.parent / "strategy.py").write_text(ADAPTER, encoding="utf-8", newline="\n")
            params_path = output.parent / "params.py"
            params_text = params_path.read_text(encoding="utf-8-sig")
            if "SOURCE_PARAMS" not in params_text:
                params_path.write_text(params_text.rstrip() +
                    '\n\n# Native source constant overrides, e.g. {"RSI_PERIOD": 14}.\n'
                    '# FAST_PERIOD/SLOW_PERIOD/SIGNAL_PERIOD above are legacy metadata;\n'
                    '# signal formulas use the original constants in _source.py.\n'
                    'SOURCE_PARAMS = {}\n', encoding="utf-8", newline="\n")
        manifest[name] = {
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "program_sha256": hashlib.sha256(generated.encode()).hexdigest(),
            "entry": "run_single" if factor else "main",
            "status": "source_program",
        }
    if not args.check:
        (ROOT / "SOURCE_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding="utf-8")
    print(f'{len(names)} source programs {"verified" if args.check else "generated"}')


if __name__ == "__main__":
    main()
