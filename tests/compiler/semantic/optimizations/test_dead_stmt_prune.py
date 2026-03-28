from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import (
    BinaryExprS,
    CastExprS,
    CallExprS,
    LiteralExprS,
    SemanticExprStmt,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticWhile,
)
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.dead_stmt_prune import dead_stmt_prune


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_dead_stmt_prune_removes_unused_pure_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var unused: i64 = 1 + 2;
            3 + 4;
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = pruned.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)
    assert isinstance(statements[0].value, LiteralExprS)
    assert statements[0].value.constant.value == 0


def test_dead_stmt_prune_rewrites_dead_effectful_statements_to_expr_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper() -> i64 {
            return 1;
        }

        fn main() -> i64 {
            var unused: i64 = helper();
            var keep: i64 = 0;
            keep = helper();
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = pruned.modules[("main",)].functions[1].body.statements

    assert len(statements) == 3
    assert isinstance(statements[0], SemanticExprStmt)
    assert isinstance(statements[0].expr, CallExprS)
    assert isinstance(statements[1], SemanticExprStmt)
    assert isinstance(statements[1].expr, CallExprS)
    assert isinstance(statements[2], SemanticReturn)


def test_dead_stmt_prune_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper() -> i64 {
            return 1;
        }

        fn main() -> i64 {
            var unused: i64 = 1;
            var x: i64 = helper();
            x = helper();
            3 + 4;
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    dead_stmt_prune(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == (
        "nifc: debug: Optimization pass dead_stmt_prune removed 2 var declarations, 1 local assignments, "
        "1 expression statements, rewrote 2 statements to preserve side effects"
    )


def test_dead_stmt_prune_preserves_dead_cast_expression_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            (u8)256.0;
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = pruned.modules[("main",)].functions[0].body.statements

    assert len(statements) == 2
    assert isinstance(statements[0], SemanticExprStmt)
    assert isinstance(statements[0].expr, CastExprS)
    assert isinstance(statements[1], SemanticReturn)


def test_dead_stmt_prune_preserves_loop_carried_updates(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var index: i64 = 0;
            var probes: i64 = 0;
            while probes < 8 {
                index = index + 1;
                if index >= 4 {
                    index = 0;
                }
                probes = probes + 1;
            }
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = pruned.modules[("main",)].functions[0].body.statements[2]

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[1], SemanticIf)
    assert len(loop_stmt.body.statements[1].then_block.statements) == 1


def test_dead_stmt_prune_removes_dead_statements_inside_while_loop(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var i: i64 = 0;
            while i < 3 {
                var dead: i64 = 1 + 2;
                i = i + 1;
            }
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = pruned.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(loop_stmt, SemanticWhile)
    assert len(loop_stmt.body.statements) == 1


def test_dead_stmt_prune_removes_dead_statements_inside_for_in_loop(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var total: i64 = 0;
            for value in i64[](3u) {
                var dead: i64 = 1 + 2;
                total = total + value;
            }
            return total;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = pruned.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(loop_stmt, SemanticForIn)
    assert len(loop_stmt.body.statements) == 1


def test_dead_stmt_prune_preserves_continue_branch_updates_needed_after_loop(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var start: i64 = 0;
            var i: i64 = 0;
            while i < 3 {
                if i == 1 {
                    i = i + 1;
                    start = i;
                    continue;
                }
                i = i + 1;
            }
            return start;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = pruned.modules[("main",)].functions[0].body.statements[2]

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[0], SemanticIf)
    assert len(loop_stmt.body.statements[0].then_block.statements) == 3


def test_dead_stmt_prune_preserves_break_branch_updates_needed_after_loop(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var found: i64 = 0;
            var i: i64 = 0;
            while i < 3 {
                if i == 1 {
                    found = 7;
                    break;
                }
                i = i + 1;
            }
            return found;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = pruned.modules[("main",)].functions[0].body.statements[2]

    assert isinstance(loop_stmt, SemanticWhile)
    assert isinstance(loop_stmt.body.statements[0], SemanticIf)
    assert len(loop_stmt.body.statements[0].then_block.statements) == 2


def test_dead_stmt_prune_preserves_trapping_shift_expression_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var value: u8 = 1u8;
            value << 8u;
            return 0;
        }
        """,
    )

    pruned = dead_stmt_prune(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = pruned.modules[("main",)].functions[0].body.statements

    assert len(statements) == 3
    assert isinstance(statements[1], SemanticExprStmt)
    assert isinstance(statements[1].expr, BinaryExprS)
    assert isinstance(statements[2], SemanticReturn)
