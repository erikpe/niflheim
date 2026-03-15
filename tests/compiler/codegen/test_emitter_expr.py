from compiler.codegen.emitter_expr import emit_expr
from tests.compiler.codegen.helpers import make_function_emit_context


def test_emitter_expr_module_emits_integer_binary_expr() -> None:
    _, generator, fn, ctx = make_function_emit_context(
        "fn f(a: i64, b: i64) -> i64 { return a + b; }",
        source_path="examples/codegen_expr.nif",
    )

    return_stmt = fn.body.statements[0]
    assert return_stmt.value is not None
    emit_expr(generator, return_stmt.value, ctx)

    assert "    push rax" in generator.asm.lines
    assert "    add rax, rcx" in generator.asm.lines


def test_emitter_expr_module_emits_numeric_cast_conversions() -> None:
    _, to_double_generator, to_double_fn, to_double_ctx = make_function_emit_context(
        "fn to_double(x: i64) -> double { return (double)x; }",
        source_path="examples/codegen_expr.nif",
        function_name="to_double",
    )

    to_double_return = to_double_fn.body.statements[0]
    assert to_double_return.value is not None
    emit_expr(to_double_generator, to_double_return.value, to_double_ctx)

    assert "    cvtsi2sd xmm0, rax" in to_double_generator.asm.lines
    assert "    movq rax, xmm0" in to_double_generator.asm.lines

    _, to_bool_generator, to_bool_fn, to_bool_ctx = make_function_emit_context(
        "fn to_bool(x: double) -> bool { return (bool)x; }",
        source_path="examples/codegen_expr.nif",
        function_name="to_bool",
    )

    to_bool_return = to_bool_fn.body.statements[0]
    assert to_bool_return.value is not None
    emit_expr(to_bool_generator, to_bool_return.value, to_bool_ctx)

    assert "    movq xmm0, rax" in to_bool_generator.asm.lines
    assert "    cvttsd2si rax, xmm0" in to_bool_generator.asm.lines
    assert "    cmp rax, 0" in to_bool_generator.asm.lines
    assert "    setne al" in to_bool_generator.asm.lines
