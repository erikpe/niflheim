from compiler.codegen.call_resolution import resolve_call_target_name, resolve_callable_value_label
from tests.compiler.codegen.helpers import make_function_emit_context


def test_call_resolution_handles_static_method_and_callable_value() -> None:
    source = """
class Math {
    static fn inc(x: i64) -> i64 {
        return x + 1;
    }
}

fn main() -> i64 {
    return Math.inc(41);
}
"""
    _, generator, fn, ctx = make_function_emit_context(
        source,
        source_path="examples/codegen.nif",
        function_name="main",
        temp_root_depth=[],
    )

    call_expr = fn.body.statements[0].value
    assert call_expr is not None
    resolved = resolve_call_target_name(call_expr.callee, ctx)
    assert resolved.name == generator.method_labels[("Math", "inc")]
    assert resolved.receiver_expr is None
    assert resolve_callable_value_label(call_expr.callee, ctx) == generator.method_labels[("Math", "inc")]