from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import (
    BinaryExprS,
    LocalRefExpr,
    SemanticAssign,
    SemanticIf,
    SemanticReturn,
    SemanticVarDecl,
    SemanticWhile,
)
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.copy_propagation import copy_propagation


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_copy_propagation_rewrites_returned_local_alias(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[2], SemanticReturn)
    assert isinstance(statements[2].value, LocalRefExpr)
    assert statements[2].value.local_id == statements[0].local_id
    assert statements[2].value.local_id != statements[1].local_id


def test_copy_propagation_invalidates_alias_after_source_reassignment(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            x = 2;
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[2], SemanticAssign)
    assert isinstance(statements[3], SemanticReturn)
    assert isinstance(statements[3].value, LocalRefExpr)
    assert statements[3].value.local_id == statements[1].local_id


def test_copy_propagation_preserves_alias_across_straight_line_nested_block(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            {
                var z: i64 = 2;
            }
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[3], SemanticReturn)
    assert isinstance(statements[3].value, LocalRefExpr)
    assert statements[3].value.local_id == statements[0].local_id


def test_copy_propagation_preserves_outer_invalidations_across_straight_line_nested_block(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            {
                x = 2;
            }
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[3], SemanticReturn)
    assert isinstance(statements[3].value, LocalRefExpr)
    assert statements[3].value.local_id == statements[1].local_id


def test_copy_propagation_is_conservative_across_if_blocks(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            if true {
                x = 2;
            }
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[2], SemanticIf)
    assert isinstance(statements[3], SemanticReturn)
    assert isinstance(statements[3].value, LocalRefExpr)
    assert statements[3].value.local_id == statements[1].local_id


def test_copy_propagation_preserves_alias_when_both_if_branches_agree(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(flag: bool) -> i64 {
            var x: i64 = 1;
            var z: i64 = 2;
            var y: i64 = z;
            if flag {
                y = x;
            } else {
                y = x;
            }
            return y;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[3], SemanticIf)
    assert isinstance(statements[4], SemanticReturn)
    assert isinstance(statements[4].value, LocalRefExpr)
    assert statements[4].value.local_id == statements[0].local_id


def test_copy_propagation_does_not_rewrite_while_condition_through_loop_carried_alias(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var start: i64 = 0;
            var i: i64 = start;
            while i < 3 {
                i = i + 1;
            }
            return i;
        }
        """,
    )

    propagated = copy_propagation(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = propagated.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[2], SemanticWhile)
    assert isinstance(statements[2].condition, BinaryExprS)
    assert isinstance(statements[2].condition.left, LocalRefExpr)
    assert statements[2].condition.left.local_id == statements[1].local_id


def test_copy_propagation_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var x: i64 = 1;
            var y: i64 = x;
            var z: i64 = y;
            return z;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    copy_propagation(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == "nifc: debug: Optimization pass copy_propagation performed 2 successful propagations"
