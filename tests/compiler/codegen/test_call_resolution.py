from tests.compiler.codegen.helpers import emit_semantic_source_asm


def test_semantic_codegen_handles_static_method_calls_and_callable_values(tmp_path) -> None:
    source = """
class Math {
    static fn add(x: i64, y: i64) -> i64 {
        return x + y;
    }
}

fn main() -> i64 {
    var f: fn(i64, i64) -> i64 = Math.add;
    return f(Math.add(20, 1), 21);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert "    call __nif_method_Math_add" in asm
    assert "    lea rax, [rip + __nif_method_Math_add]" in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_semantic_codegen_handles_runtime_array_len_calls(tmp_path) -> None:
    asm = emit_semantic_source_asm(
        tmp_path,
        """
        fn main(xs: i64[]) -> u64 {
            return xs.len();
        }
        """,
    )

    assert "    call rt_array_len" in asm


def test_semantic_codegen_dispatches_array_methods_to_runtime_calls(tmp_path) -> None:
    source = """
fn main(values: i64[], refs: Obj[]) -> i64 {
    values.index_set(0, 7);
    refs.slice_set(0, 1, refs);
    return values.iter_get(0);
}
"""
    asm = emit_semantic_source_asm(tmp_path, source)

    assert "    call rt_array_set_i64" in asm
    assert "    call rt_array_set_slice_ref" in asm
    assert "    call rt_array_get_i64" in asm
