from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import CallExprS, FunctionCallTarget, InstanceMethodCallTarget, IntConstant, LiteralExprS, SemanticIf, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.copy_propagation import copy_propagation
from compiler.semantic.optimizations.constant_fold import constant_fold
from compiler.semantic.optimizations.dead_store_elimination import dead_store_elimination
from compiler.semantic.optimizations.dead_stmt_prune import dead_stmt_prune
from compiler.semantic.optimizations.flow_sensitive_type_narrowing import flow_sensitive_type_narrowing
from compiler.semantic.optimizations.interface_call_devirtualization import interface_call_devirtualization
from compiler.semantic.optimizations.pipeline import (
    DEFAULT_SEMANTIC_OPTIMIZATION_PASSES,
    SemanticOptimizationPass,
    optimize_semantic_program,
)
from compiler.semantic.optimizations.unreachable_prune import unreachable_prune
from compiler.semantic.optimizations.redundant_cast_elimination import redundant_cast_elimination
from compiler.semantic.optimizations.simplify_control_flow import simplify_control_flow


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
    expected = unreachable_prune(
        dead_stmt_prune(
            simplify_control_flow(
                constant_fold(
                    dead_store_elimination(
                        redundant_cast_elimination(
                            interface_call_devirtualization(
                                flow_sensitive_type_narrowing(copy_propagation(simplify_control_flow(constant_fold(semantic))))
                            )
                        )
                    )
                )
            )
        )
    )

    assert [optimization_pass.name for optimization_pass in DEFAULT_SEMANTIC_OPTIMIZATION_PASSES] == [
        "constant_fold",
        "simplify_control_flow",
        "copy_propagation",
        "flow_sensitive_type_narrowing",
        "interface_call_devirtualization",
        "redundant_cast_elimination",
        "dead_store_elimination",
        "constant_fold",
        "simplify_control_flow",
        "dead_stmt_prune",
        "unreachable_prune",
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
    assert isinstance(return_stmt.value, CallExprS)
    assert isinstance(return_stmt.value.target, FunctionCallTarget)
    assert isinstance(return_stmt.value.args[0], LiteralExprS)
    assert isinstance(return_stmt.value.args[0].constant, IntConstant)
    assert return_stmt.value.args[0].constant.value == 3


def test_optimize_semantic_program_devirtualizes_interface_calls_after_narrowing(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main(value: Obj) -> u64 {
            if value is Key {
                var hashable: Hashable = (Hashable)value;
                return hashable.hash_code();
            }
            return 0u;
        }
        """,
    )

    optimized = optimize_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[1], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[1].value, CallExprS)
    assert isinstance(if_stmt.then_block.statements[1].value.target, InstanceMethodCallTarget)
    assert if_stmt.then_block.statements[1].value.target.method_id.name == "hash_code"
    assert if_stmt.then_block.statements[1].value.target.access.receiver_type_ref.class_id is not None
    assert if_stmt.then_block.statements[1].value.target.access.receiver_type_ref.class_id.name == "Key"
