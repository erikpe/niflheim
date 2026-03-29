from compiler.codegen.abi.array import array_length_operand
from compiler.codegen.abi.runtime import (
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
)
from compiler.common.collection_protocols import ArrayRuntimeKind
from tests.compiler.codegen.helpers import emit_source_asm


def test_codegen_handles_static_method_calls_and_callable_values(tmp_path) -> None:
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
    asm = emit_source_asm(tmp_path, source)

    assert "    call __nif_method_Math_add" in asm
    assert "    lea rax, [rip + __nif_method_Math_add]" in asm
    assert "    mov r11, rax" in asm
    assert "    call r11" in asm


def test_codegen_handles_structural_array_len_via_direct_load(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main(xs: i64[]) -> u64 {
            return xs.len();
        }
        """,
    )

    assert f"    mov rax, {array_length_operand('rax')}" in asm
    assert "    call rt_array_len" not in asm


def test_codegen_dispatches_array_methods_to_runtime_calls(tmp_path) -> None:
    source = """
fn main(values: i64[], refs: Obj[]) -> i64 {
    values.index_set(0, 7);
    refs.slice_set(0, 1, refs);
    return values.iter_get(0);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in asm
    assert f"    call {ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in asm
