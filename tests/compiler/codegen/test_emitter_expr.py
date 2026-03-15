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
