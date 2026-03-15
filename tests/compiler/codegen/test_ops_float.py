from compiler.codegen.asm import AsmBuilder
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double


def test_ops_float_emitters_cover_negation_and_nan_aware_comparison() -> None:
    builder = AsmBuilder()

    emit_unary_negate_double(builder)
    ok = emit_double_binary_op(builder, "!=")

    assert ok is True
    assert "    xorpd xmm1, xmm1" in builder.lines
    assert "    ucomisd xmm0, xmm1" in builder.lines
    assert "    setp dl" in builder.lines
    assert "    or al, dl" in builder.lines