from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import CallExprS, CastExprS, LocalRefExpr, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.redundant_cast_elimination import redundant_cast_elimination


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_redundant_cast_elimination_removes_identity_return_cast(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var value: i64 = 7;
            return (i64)value;
        }
        """,
    )

    optimized = redundant_cast_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)


def test_redundant_cast_elimination_removes_nested_identity_casts(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn helper(value: i64) -> i64 {
            return value;
        }

        fn main() -> i64 {
            return (i64)((i64)helper(7));
        }
        """,
    )

    optimized = redundant_cast_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CallExprS)


def test_redundant_cast_elimination_preserves_value_changing_casts(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> u8 {
            return (u8)258.0;
        }
        """,
    )

    optimized = redundant_cast_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CastExprS)


def test_redundant_cast_elimination_preserves_reference_compatibility_casts(tmp_path: Path) -> None:
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

        fn main() -> Hashable {
            var value: Obj = Key();
            return (Hashable)value;
        }
        """,
    )

    optimized = redundant_cast_elimination(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CastExprS)


def test_redundant_cast_elimination_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var value: i64 = 7;
            var alias: i64 = (i64)value;
            return (i64)alias;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    redundant_cast_elimination(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == "nifc: debug: Optimization pass redundant_cast_elimination removed 2 redundant casts"
