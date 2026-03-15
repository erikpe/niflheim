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


def test_call_resolution_handles_runtime_call_names() -> None:
    _, _generator, fn, ctx = make_function_emit_context(
        "fn main(xs: i64[]) -> u64 { return rt_array_len(xs); }",
        source_path="examples/codegen.nif",
        function_name="main",
        temp_root_depth=[],
    )

    call_expr = fn.body.statements[0].value
    assert call_expr is not None
    resolved = resolve_call_target_name(call_expr.callee, ctx)

    assert resolved.name == "rt_array_len"
    assert resolved.receiver_expr is None
    assert resolved.return_type_name == "u64"


def test_call_resolution_dispatches_array_methods_to_runtime_calls() -> None:
    source = """
fn main(values: i64[], refs: Obj[]) -> i64 {
    values.index_set(0, 7);
    refs.slice_set(0, 1, refs);
    return values.iter_get(0);
}
"""
    _, _generator, fn, ctx = make_function_emit_context(
        source,
        source_path="examples/codegen.nif",
        function_name="main",
        temp_root_depth=[],
    )

    set_call = fn.body.statements[0].expression
    slice_set_call = fn.body.statements[1].expression
    get_call = fn.body.statements[2].value

    set_resolved = resolve_call_target_name(set_call.callee, ctx)
    slice_set_resolved = resolve_call_target_name(slice_set_call.callee, ctx)
    get_resolved = resolve_call_target_name(get_call.callee, ctx)

    assert set_resolved.name == "rt_array_set_i64"
    assert set_resolved.return_type_name == "unit"
    assert slice_set_resolved.name == "rt_array_set_slice_ref"
    assert slice_set_resolved.return_type_name == "unit"
    assert get_resolved.name == "rt_array_get_i64"
    assert get_resolved.return_type_name == "i64"
