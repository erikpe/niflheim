from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import BoolConstant, CastExprS, LiteralExprS, LocalRefExpr, SemanticIf, SemanticReturn, SemanticVarDecl
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.flow_sensitive_type_narrowing import flow_sensitive_type_narrowing


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _run_flow_sensitive_type_narrowing(tmp_path: Path):
    return flow_sensitive_type_narrowing(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))


def test_flow_sensitive_type_narrowing_removes_redundant_cast_inside_positive_type_test_branch(tmp_path: Path) -> None:
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

        fn main(value: Obj) -> Hashable {
            if value is Hashable {
                return (Hashable)value;
            }
            return null;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[0], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[0].value, LocalRefExpr)


def test_flow_sensitive_type_narrowing_folds_nested_type_test_inside_positive_branch(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Key {
            value: i64;
        }

        fn main(value: Obj) -> bool {
            if value is Key {
                return value is Key;
            }
            return false;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    if_stmt = optimized.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(if_stmt, SemanticIf)
    assert isinstance(if_stmt.then_block.statements[0], SemanticReturn)
    assert isinstance(if_stmt.then_block.statements[0].value, LiteralExprS)
    assert isinstance(if_stmt.then_block.statements[0].value.constant, BoolConstant)
    assert if_stmt.then_block.statements[0].value.constant.value is True


def test_flow_sensitive_type_narrowing_removes_repeated_cast_after_successful_cast(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Key {
            value: i64;
        }

        fn main(value: Obj) -> Key {
            var key: Key = (Key)value;
            return (Key)value;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)


def test_flow_sensitive_type_narrowing_folds_later_type_test_after_successful_cast(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Key {
            value: i64;
        }

        fn main(value: Obj) -> bool {
            var key: Key = (Key)value;
            return value is Key;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LiteralExprS)
    assert isinstance(return_stmt.value.constant, BoolConstant)
    assert return_stmt.value.constant.value is True


def test_flow_sensitive_type_narrowing_handles_negated_type_test_fallthrough(tmp_path: Path) -> None:
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

        fn main(value: Obj) -> Hashable {
            if !(value is Hashable) {
                return null;
            }
            return (Hashable)value;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)


def test_flow_sensitive_type_narrowing_is_conservative_across_if_merge(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Key {
            value: i64;
        }

        fn main(flag: bool, value: Obj) -> Key {
            if flag {
                var key: Key = (Key)value;
            }
            return (Key)value;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    return_stmt = optimized.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CastExprS)


def test_flow_sensitive_type_narrowing_invalidates_facts_after_reassignment(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Key {
            value: i64;
        }

        fn main(first: Obj, second: Obj) -> Key {
            var value: Obj = first;
            var key: Key = (Key)value;
            value = second;
            return (Key)value;
        }
        """,
    )

    optimized = _run_flow_sensitive_type_narrowing(tmp_path)
    statements = optimized.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[3], SemanticReturn)
    assert isinstance(statements[3].value, CastExprS)


def test_flow_sensitive_type_narrowing_logs_exact_summary_counts(tmp_path: Path, capsys) -> None:
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

        fn main(value: Obj) -> Hashable {
            if value is Hashable {
                return (Hashable)value;
            }
            return null;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    flow_sensitive_type_narrowing(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == (
        "nifc: debug: Optimization pass flow_sensitive_type_narrowing removed 1 checked casts, folded 0 type tests, "
        "seeded 1 branch facts, seeded 0 cast facts"
    )
