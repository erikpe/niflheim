from compiler.codegen.asm import AsmBuilder
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double
from compiler.semantic.operations import BinaryOpKind


def test_ops_float_emitters_cover_negation_and_nan_aware_comparison() -> None:
    builder = AsmBuilder()

    emit_unary_negate_double(builder)
    ok = emit_double_binary_op(builder, BinaryOpKind.NOT_EQUAL)

    assert ok is True
    assert "    xorpd xmm1, xmm1" in builder.lines
    assert "    ucomisd xmm0, xmm1" in builder.lines
    assert "    setp dl" in builder.lines
    assert "    or al, dl" in builder.lines


def test_ops_float_emitters_cover_arithmetic_ops() -> None:
    expected_mnemonics = {
        BinaryOpKind.ADD: "addsd",
        BinaryOpKind.SUBTRACT: "subsd",
        BinaryOpKind.MULTIPLY: "mulsd",
        BinaryOpKind.DIVIDE: "divsd",
    }

    for operator, mnemonic in expected_mnemonics.items():
        builder = AsmBuilder()

        ok = emit_double_binary_op(builder, operator)

        assert ok is True
        assert f"    {mnemonic} xmm0, xmm1" in builder.lines
        assert "    movq rax, xmm0" in builder.lines


def test_ops_float_emitters_cover_nan_aware_equality() -> None:
    builder = AsmBuilder()

    ok = emit_double_binary_op(builder, BinaryOpKind.EQUAL)

    assert ok is True
    assert "    ucomisd xmm0, xmm1" in builder.lines
    assert "    sete al" in builder.lines
    assert "    setnp dl" in builder.lines
    assert "    and al, dl" in builder.lines
    assert "    movzx rax, al" in builder.lines
