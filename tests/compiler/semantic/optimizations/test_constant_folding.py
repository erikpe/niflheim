from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.semantic.ir import BoolConstant, BinaryExprS, FunctionCallExpr, IntConstant, LiteralExprS, SemanticReturn
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
