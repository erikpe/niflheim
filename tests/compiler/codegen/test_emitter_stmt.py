from compiler.codegen.emitter_stmt import emit_statement
from tests.compiler.codegen.helpers import make_function_emit_context


def test_emitter_stmt_module_emits_while_control_flow() -> None:
    source = """
fn loop_to(limit: i64) -> i64 {
    var i: i64 = 0;
    while i < limit {
        i = i + 1;
    }
    return i;
}
"""
    _, generator, fn, ctx = make_function_emit_context(
        source,
        source_path="examples/codegen_stmt.nif",
    )

    emit_statement(generator, fn.body.statements[1], ".Lf_epilogue", "i64", ctx, loop_labels=[])

    assert any(line.startswith(".Lloop_to_while_start_") for line in generator.asm.lines)
    assert any(line.startswith(".Lloop_to_while_end_") for line in generator.asm.lines)
    assert "    je .Lloop_to_while_end_1" in generator.asm.lines or any(
        line.startswith("    je .Lloop_to_while_end_") for line in generator.asm.lines
    )