from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import BoolConstant, BinaryExprS, CastExprS, FloatConstant, FunctionCallExpr, IntConstant, LiteralExprS, SemanticReturn
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.optimizations.constant_folding import fold_constants


def _write(path: Path, text: str) -> None:
    path.write_text(text.strip() + "\n", encoding="utf-8")


def test_fold_constants_folds_literal_arithmetic_and_boolean_exprs(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn math() -> i64 {
            return (1 + 2) * 3 - 4;
        }

        fn flags() -> bool {
            return (1 < 2) && (3 > 1);
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    math_return = folded.modules[("main",)].functions[0].body.statements[0]
    flags_return = folded.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(math_return, SemanticReturn)
    assert isinstance(math_return.value, LiteralExprS)
    assert isinstance(math_return.value.constant, IntConstant)
    assert math_return.value.constant.value == 5

    assert isinstance(flags_return, SemanticReturn)
    assert isinstance(flags_return.value, LiteralExprS)
    assert isinstance(flags_return.value.constant, BoolConstant)
    assert flags_return.value.constant.value is True


def test_fold_constants_folds_field_initializers_and_call_arguments(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64 = (1 + 2) * 4;
        }

        fn identity(value: i64) -> i64 {
            return value;
        }

        fn call() -> i64 {
            return identity(1 + 2);
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    field_initializer = folded.modules[("main",)].classes[0].fields[0].initializer
    call_return = folded.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(field_initializer, LiteralExprS)
    assert isinstance(field_initializer.constant, IntConstant)
    assert field_initializer.constant.value == 12

    assert isinstance(call_return, SemanticReturn)
    assert isinstance(call_return.value, FunctionCallExpr)
    assert isinstance(call_return.value.args[0], LiteralExprS)
    assert isinstance(call_return.value.args[0].constant, IntConstant)
    assert call_return.value.args[0].constant.value == 3


def test_fold_constants_preserves_runtime_checked_integer_operations(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn div_zero() -> i64 {
            return 1 / 0;
        }

        fn bad_shift() -> u8 {
            return 1u8 << 8u;
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    div_return = folded.modules[("main",)].functions[0].body.statements[0]
    shift_return = folded.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(div_return, SemanticReturn)
    assert isinstance(div_return.value, BinaryExprS)

    assert isinstance(shift_return, SemanticReturn)
    assert isinstance(shift_return.value, BinaryExprS)


def test_fold_constants_folds_conservative_literal_casts(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            var as_double: double = (double)7;
            var as_u8: u8 = (u8)258;
            var as_bool_from_int: bool = (bool)7;
            var as_i64_from_double: i64 = (i64)7.9;
            var as_u64_from_double: u64 = (u64)7.9;
            var as_bool_from_double: bool = (bool)0.5;
            return (i64)as_u8 + as_i64_from_double;
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    statements = folded.modules[("main",)].functions[0].body.statements

    as_double = statements[0]
    as_u8 = statements[1]
    as_bool_from_int = statements[2]
    as_i64_from_double = statements[3]
    as_u64_from_double = statements[4]
    as_bool_from_double = statements[5]

    assert isinstance(as_double.initializer, LiteralExprS)
    assert isinstance(as_double.initializer.constant, FloatConstant)
    assert as_double.initializer.constant.value == 7.0

    assert isinstance(as_u8.initializer, LiteralExprS)
    assert isinstance(as_u8.initializer.constant, IntConstant)
    assert as_u8.initializer.constant.type_name == "u8"
    assert as_u8.initializer.constant.value == 2

    assert isinstance(as_bool_from_int.initializer, LiteralExprS)
    assert isinstance(as_bool_from_int.initializer.constant, BoolConstant)
    assert as_bool_from_int.initializer.constant.value is True

    assert isinstance(as_i64_from_double.initializer, LiteralExprS)
    assert isinstance(as_i64_from_double.initializer.constant, IntConstant)
    assert as_i64_from_double.initializer.constant.type_name == "i64"
    assert as_i64_from_double.initializer.constant.value == 7

    assert isinstance(as_u64_from_double.initializer, LiteralExprS)
    assert isinstance(as_u64_from_double.initializer.constant, IntConstant)
    assert as_u64_from_double.initializer.constant.type_name == "u64"
    assert as_u64_from_double.initializer.constant.value == 7

    assert isinstance(as_bool_from_double.initializer, LiteralExprS)
    assert isinstance(as_bool_from_double.initializer.constant, BoolConstant)
    assert as_bool_from_double.initializer.constant.value is True


def test_fold_constants_preserves_casts_without_safe_backend_equivalent(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn large_to_i64() -> i64 {
            return (i64)9223372036854775808.0;
        }

        fn large_to_u8() -> u8 {
            return (u8)256.0;
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    large_to_i64_return = folded.modules[("main",)].functions[0].body.statements[0]
    large_to_u8_return = folded.modules[("main",)].functions[1].body.statements[0]

    assert isinstance(large_to_i64_return, SemanticReturn)
    assert isinstance(large_to_i64_return.value, CastExprS)

    assert isinstance(large_to_u8_return, SemanticReturn)
    assert isinstance(large_to_u8_return.value, CastExprS)


def test_fold_constants_folds_u64_to_double_using_unsigned_numeric_conversion(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> double {
            return (double)18446744073709551615u;
        }
        """,
    )

    folded = fold_constants(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    return_stmt = folded.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LiteralExprS)
    assert isinstance(return_stmt.value.constant, FloatConstant)
    assert return_stmt.value.constant.value == float(18446744073709551615)
