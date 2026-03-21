from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import FunctionCallExpr, IntConstant, LiteralExprS, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.constant_folding import fold_constants
from compiler.semantic.optimizations.pipeline import (
    DEFAULT_SEMANTIC_OPTIMIZATION_PASSES,
    SemanticOptimizationPass,
    optimize_semantic_program,
)
from compiler.semantic.optimizations.reachability import prune_unreachable_semantic


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_optimize_semantic_program_uses_default_pass_pipeline(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn dead() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))

    optimized = optimize_semantic_program(semantic)
    expected = prune_unreachable_semantic(fold_constants(semantic))

    assert [optimization_pass.name for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES] == [
        "constant_fold",
        "prune_unreachable",
    ]
    assert optimized == expected


def test_optimize_semantic_program_applies_passes_in_order(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    applied: list[str] = []

    def record_first(program):
        applied.append("first")
        return program

    def record_second(program):
        applied.append("second")
        return program

    optimized = optimize_semantic_program(
        semantic,
        passes=(
            SemanticOptimizationPass(name="first", transform=record_first),
            SemanticOptimizationPass(name="second", transform=record_second),
        ),
    )

    assert optimized == semantic
    assert applied == ["first", "second"]


def test_optimize_semantic_program_folds_constants_before_pruning(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper(value: i64) -> i64 {
            return value;
        }

        fn main() -> i64 {
            return helper(1 + 2);
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, FunctionCallExpr)
    assert isinstance(return_stmt.value.args[0], LiteralExprS)
    assert isinstance(return_stmt.value.args[0].constant, IntConstant)
    assert return_stmt.value.args[0].constant.value == 3
