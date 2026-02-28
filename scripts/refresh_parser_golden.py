#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compiler.ast_dump import ast_to_debug_json
from compiler.lexer import lex
from compiler.parser import parse, parse_expression


@dataclass(frozen=True)
class GoldenTarget:
    source_file: str
    golden_file: str
    parse_mode: str  # "module" | "expression"


TARGETS: tuple[GoldenTarget, ...] = (
    GoldenTarget(
        source_file="module_shape.nif",
        golden_file="module_shape.golden.json",
        parse_mode="module",
    ),
    GoldenTarget(
        source_file="expression_shape.nif",
        golden_file="expression_shape.golden.json",
        parse_mode="expression",
    ),
    GoldenTarget(
        source_file="module_shape_private_arrays_control_flow.nif",
        golden_file="module_shape_private_arrays_control_flow.golden.json",
        parse_mode="module",
    ),
    GoldenTarget(
        source_file="module_shape_qualified_calls_and_casts.nif",
        golden_file="module_shape_qualified_calls_and_casts.golden.json",
        parse_mode="module",
    ),
    GoldenTarget(
        source_file="module_shape_structural_sugar.nif",
        golden_file="module_shape_structural_sugar.golden.json",
        parse_mode="module",
    ),
    GoldenTarget(
        source_file="expression_shape_slice_chain.nif",
        golden_file="expression_shape_slice_chain.golden.json",
        parse_mode="expression",
    ),
    GoldenTarget(
        source_file="expression_shape_qualified_casts.nif",
        golden_file="expression_shape_qualified_casts.golden.json",
        parse_mode="expression",
    ),
    GoldenTarget(
        source_file="expression_shape_logical_and_compare.nif",
        golden_file="expression_shape_logical_and_compare.golden.json",
        parse_mode="expression",
    ),
)


def refresh_golden_files(golden_dir: Path, *, include_spans: bool) -> None:
    for target in TARGETS:
        source_path = golden_dir / target.source_file
        golden_path = golden_dir / target.golden_file

        source_text = source_path.read_text(encoding="utf-8")
        tokens = lex(source_text, source_path=source_path.as_posix())

        if target.parse_mode == "module":
            ast = parse(tokens)
        elif target.parse_mode == "expression":
            ast = parse_expression(tokens)
        else:
            raise ValueError(f"Unknown parse mode: {target.parse_mode}")

        golden_text = ast_to_debug_json(ast, include_spans=include_spans)
        golden_path.write_text(golden_text + "\n", encoding="utf-8")
        print(f"Updated {golden_path.as_posix()}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh parser AST golden JSON snapshots.",
    )
    parser.add_argument(
        "--golden-dir",
        default="tests/compiler/parser/golden",
        help="Directory containing parser golden .nif and .golden.json files.",
    )
    parser.add_argument(
        "--include-spans",
        action="store_true",
        help="Include span fields in output JSON (disabled by default).",
    )

    args = parser.parse_args()
    golden_dir = Path(args.golden_dir)

    if not golden_dir.exists():
        raise FileNotFoundError(f"Golden directory does not exist: {golden_dir}")

    refresh_golden_files(golden_dir, include_spans=args.include_spans)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
