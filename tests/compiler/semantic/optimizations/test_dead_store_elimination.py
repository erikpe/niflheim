from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import CallExprS, SemanticAssign, SemanticExprStmt, SemanticReturn, SemanticWhile
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.dead_store_elimination import dead_store_elimination


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_dead_store_elimination_removes_dead_local_stores(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var unused: i64 = 1 + 2;
            var value: i64 = 0;
            value = 7;
            return 0;
        }
        """,
    )

    optimized = dead_store_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = optimized.modules[("main",)].functions[0].body.statements

    assert len(statements) == 1
    assert isinstance(statements[0], SemanticReturn)


def test_dead_store_elimination_rewrites_effectful_dead_stores_to_expr_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper() -> i64 {
            return 1;
        }

        fn main() -> i64 {
            var unused: i64 = helper();
            var value: i64 = 0;
            value = helper();
            return 0;
        }
        """,
    )

    optimized = dead_store_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = optimized.modules[("main",)].functions[1].body.statements

    assert len(statements) == 3
    assert isinstance(statements[0], SemanticExprStmt)
    assert isinstance(statements[0].expr, CallExprS)
    assert isinstance(statements[1], SemanticExprStmt)
    assert isinstance(statements[1].expr, CallExprS)
    assert isinstance(statements[-1], SemanticReturn)


def test_dead_store_elimination_preserves_expression_statements(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            1 + 2;
            return 0;
        }
        """,
    )

    optimized = dead_store_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = optimized.modules[("main",)].functions[0].body.statements

    assert len(statements) == 2
    assert isinstance(statements[0], SemanticExprStmt)
    assert isinstance(statements[1], SemanticReturn)


def test_dead_store_elimination_preserves_loop_carried_updates(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var i: i64 = 0;
            while i < 3 {
                i = i + 1;
            }
            return i;
        }
        """,
    )

    optimized = dead_store_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    loop_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(loop_stmt, SemanticWhile)
    assert len(loop_stmt.body.statements) == 1
    assert isinstance(loop_stmt.body.statements[0], SemanticAssign)


def test_dead_store_elimination_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
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
            return 0;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    dead_store_elimination(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == (
        "nifc: debug: Optimization pass dead_store_elimination removed 2 var declarations, 1 local assignments, "
        "rewrote 2 statements to preserve side effects"
    )