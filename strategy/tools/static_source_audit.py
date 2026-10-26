"""Read-only AST inventory of the first four local strategy categories.

This parses source text and never imports or executes a strategy or TqSdk.
"""
from __future__ import annotations

import ast
import argparse
import re
from pathlib import Path


LOCAL = Path(__file__).resolve().parents[1]
ORIGINAL = Path(r"C:\Users\Administrator\Desktop\ChenLiyuan\期货量化\tqsdk-strategies-main\strategies")


def category_packages() -> list[str]:
    tree = ast.parse((LOCAL / "strategies" / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "_CATEGORY_GROUPS":
            groups = ast.literal_eval(node.value)
            return [name for group in list(groups.values())[:4] for name in sorted(group)]
    raise RuntimeError("Strategy category list not found")


def summarize(path: Path) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                if name.isupper() and not any(word in name for word in ("ACCOUNT", "PASSWORD", "AUTH", "SYMBOL", "DATE", "BALANCE")):
                    value = ast.unparse(node.value)
                    if len(value) < 130:
                        out.append(f"CONST {name}={value}")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("calc") or node.name.startswith("calculate") or node.name.startswith("get_") or node.name in {"main", "run_single", "on_bar", "update", "generate_signal", "check_signal"}:
            out.append(f"FUNC {node.name} @ {node.lineno}")
            for nested in ast.walk(node):
                if isinstance(nested, ast.If):
                    desc = ast.unparse(nested.test)
                    if len(desc) < 170:
                        out.append(f"  IF {desc}")
                elif isinstance(nested, ast.Call) and isinstance(nested.func, ast.Attribute) and nested.func.attr in {"set_target_volume", "get_kline_serial"}:
                    out.append(f"  CALL {ast.unparse(nested)}")
    return "\n".join(out)


def factor_comparison(packages: list[str]) -> None:
    local_tree = ast.parse((LOCAL / "strategies" / "_source_factor.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in local_tree.body if isinstance(node, ast.FunctionDef)}
    wanted = ("latest", "clamp", "rolling_zscore", "calc_atr", "calc_rsi",
              "calc_mfi", "calc_kama", "calc_nvi", "open_interest_series",
              "calculate_features", "weighted_score", "score_to_volume")
    for name in packages:
        wrapper_text = (LOCAL / "strategies" / name / "strategy.py").read_text(encoding="utf-8")
        if "_source_factor import" not in wrapper_text:
            continue
        source_tree = ast.parse((ORIGINAL / f"{name}.py").read_text(encoding="utf-8"))
        source_functions = {node.name: node for node in source_tree.body if isinstance(node, ast.FunctionDef)}
        mismatches = [fn for fn in wanted if fn not in functions or fn not in source_functions or
                      ast.dump(functions[fn], include_attributes=False) !=
                      ast.dump(source_functions[fn], include_attributes=False)]
        source_weights = next((ast.literal_eval(node.value) for node in source_tree.body
                               if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                               t.id == "FACTOR_WEIGHTS" for t in node.targets)), None)
        wrapper_tree = ast.parse(wrapper_text)
        wrapper_weights = None
        for node in ast.walk(wrapper_tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                    t.id == "FACTOR_WEIGHTS" for t in node.targets):
                wrapper_weights = ast.literal_eval(node.value)
        print(f"{name}: feature/helper AST differences={mismatches}; weights_equal={source_weights == wrapper_weights}")


def verify_inventory(packages: list[str]) -> None:
    rules_dir = LOCAL / "strategies"
    rule_paths = [rules_dir / name for name in (
        "_source_rules.py", "_source_rules_mid.py", "_source_rules_standard.py",
        "_source_rules_late.py", "_source_rules_complex.py", "_source_rules_levels.py")]
    rule_names: set[str] = set()
    source_lengths: set[str] = set()
    for path in rule_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                keys = {key.value for key in node.value.keys if isinstance(key, ast.Constant)
                        and isinstance(key.value, str)}
                names = {target.id for target in node.targets if isinstance(target, ast.Name)}
                if names & {"RULES", "_RULES"}:
                    rule_names |= keys
                if "_SOURCE_LENGTHS" in names:
                    source_lengths |= keys
    errors = []
    for name in packages:
        source = ORIGINAL / f"{name}.py"
        wrapper = rules_dir / name / "strategy.py"
        for path in (source, wrapper, rules_dir / name / "params.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError) as exc:
                errors.append(f"{name}: {path.name}: {exc}")
        text = wrapper.read_text(encoding="utf-8")
        if "_source_rules import" in text and name not in rule_names:
            errors.append(f"{name}: missing rule")
    missing_lengths = sorted(rule_names - source_lengths - {"57_adaptive_volatility_breakout"})
    extra_lengths = sorted(source_lengths - rule_names)
    document = (LOCAL / "SOURCE_STRATEGY_ALIGNMENT.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"\[([A-Za-z0-9_]+)\]\(\./strategies/\1/strategy\.py\)", document))
    missing_documentation = sorted(set(packages) - documented)
    print(f"categories={len(packages)} mapped_rules={len(rule_names)} source_lengths={len(source_lengths)}")
    print(f"missing_lengths={missing_lengths} extra_lengths={extra_lengths}")
    print(f"documented={len(documented)} missing_documentation={missing_documentation}")
    print(f"parse_or_mapping_errors={errors}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--factors", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    packages = category_packages()
    if args.factors:
        factor_comparison(packages)
        return
    if args.verify:
        verify_inventory(packages)
        return
    for name in (args.names or packages):
        if name not in packages:
            raise ValueError(name)
        source = ORIGINAL / f"{name}.py"
        wrapper = LOCAL / "strategies" / name / "strategy.py"
        print(f"\n### {name}")
        print(f"SOURCE {source.exists()}  LOCAL {wrapper.exists()}")
        if source.exists():
            print(summarize(source))
        if wrapper.exists():
            print("WRAPPER", wrapper.read_text(encoding="utf-8").strip()[:550])


if __name__ == "__main__":
    main()
