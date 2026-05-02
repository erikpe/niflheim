from __future__ import annotations

from pathlib import Path

from compiler.common.logging import configure_logging, resolve_log_settings
from compiler.resolver import resolve_program
from compiler.semantic.ir import BinaryExprS, LocalRefExpr, SemanticFunction, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.algebraic_simplify import algebraic_simplify


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def _function(program, name: str) -> SemanticFunction:
    return next(fn for fn in program.modules[("main",)].functions if fn.function_id.name == name)


def _return_value(fn: SemanticFunction):
    return_stmt = fn.body.statements[0]
    assert isinstance(return_stmt, SemanticReturn)
    return return_stmt.value


def test_algebraic_simplify_removes_integer_identity_operands(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn add_zero(value: i64) -> i64 {
            return value + 0;
        }

        fn multiply_one(value: u64) -> u64 {
            return 1u * value;
        }

        fn shift_zero(value: u8) -> u8 {
            return value << 0u;
        }

        fn and_all_ones(value: u8) -> u8 {
            return value & 255u8;
        }
        """,
    )

    optimized = algebraic_simplify(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert isinstance(_return_value(_function(optimized, "add_zero")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "multiply_one")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "shift_zero")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "and_all_ones")), LocalRefExpr)


def test_algebraic_simplify_removes_boolean_identities_and_double_negation(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn and_true(value: bool) -> bool {
            return !!(value && true);
        }

        fn false_or(value: bool) -> bool {
            return false || value;
        }

        fn equals_true(value: bool) -> bool {
            return value == true;
        }

        fn not_equals_false(value: bool) -> bool {
            return false != value;
        }
        """,
    )

    optimized = algebraic_simplify(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert isinstance(_return_value(_function(optimized, "and_true")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "false_or")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "equals_true")), LocalRefExpr)
    assert isinstance(_return_value(_function(optimized, "not_equals_false")), LocalRefExpr)


def test_algebraic_simplify_preserves_effectful_operands_when_identity_does_not_preserve_evaluation(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn int_value() -> i64 {
            return 7;
        }

        fn bool_value() -> bool {
            return true;
        }

        fn multiply_zero() -> i64 {
            return int_value() * 0;
        }

        fn and_false() -> bool {
            return bool_value() && false;
        }

        fn or_true() -> bool {
            return bool_value() || true;
        }
        """,
    )

    optimized = algebraic_simplify(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))

    assert isinstance(_return_value(_function(optimized, "multiply_zero")), BinaryExprS)
    assert isinstance(_return_value(_function(optimized, "and_false")), BinaryExprS)
    assert isinstance(_return_value(_function(optimized, "or_true")), BinaryExprS)


def test_algebraic_simplify_logs_exact_summary_count(tmp_path: Path, capsys) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(value: i64, flag: bool) -> i64 {
            var simplified_bool: bool = !!(flag || false);
            return (value + 0) * 1;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    capsys.readouterr()
    configure_logging(resolve_log_settings("debug", verbose=1, quiet=0))

    algebraic_simplify(semantic)
    captured = capsys.readouterr()

    assert captured.err.strip() == "nifc: debug: Optimization pass algebraic_simplify simplified 4 expressions"
