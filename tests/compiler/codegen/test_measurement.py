from compiler.codegen.abi.runtime import (
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_INDEX_SET_RUNTIME_CALLS,
    ARRAY_LEN_RUNTIME_CALL,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
    ARRAY_SLICE_SET_RUNTIME_CALLS,
)
from compiler.codegen.measurement import analyze_assembly_metrics, extract_function_asm
from compiler.common.collection_protocols import ArrayRuntimeKind
from tests.compiler.codegen.helpers import emit_source_asm


def test_analyze_assembly_metrics_counts_scaffolding_markers() -> None:
    asm = """demo:
    mov rax, 1
    # mirror named reference slots into shadow-stack slots
    mov rax, qword ptr [rbp - 8]
    mov qword ptr [rbp - 16], rax
    call rt_root_slot_store
    # runtime safepoint hook
    # clear dead named reference shadow-stack slots
    mov qword ptr [rbp - 16], 0
.Ldemo_epilogue:
"""

    metrics = analyze_assembly_metrics(asm)

    assert metrics.line_count == 10
    assert metrics.instruction_count == 5
    assert metrics.root_slot_store_call_count == 1
    assert metrics.named_root_sync_block_count == 1
    assert metrics.dead_named_root_clear_block_count == 1
    assert metrics.safepoint_hook_count == 1


def test_extract_function_asm_returns_requested_function_body() -> None:
    asm = """
first:
    mov rax, 1
.Lfirst_epilogue:
second:
    mov rax, 2
.Lsecond_epilogue:
"""

    extracted = extract_function_asm(asm, "second")

    assert extracted == "second:\n    mov rax, 2\n"


def test_extract_function_asm_returns_none_for_missing_symbol() -> None:
    assert extract_function_asm("main:\n    ret\n", "missing") is None


def test_emit_source_asm_can_disable_collection_fast_paths_for_measurement(tmp_path) -> None:
    source = """
fn measure(values: i64[]) -> i64 {
    var total: i64 = 0;
    for value in values {
        total = total + value;
    }
    return total + values[0] + (i64)values.len();
}

fn main() -> i64 {
    var values: i64[] = i64[](2u);
    values[0] = 4;
    values[1] = 6;
    return measure(values);
}
"""

    asm = emit_source_asm(tmp_path, source, collection_fast_paths_enabled=False)
    measure_asm = extract_function_asm(asm, "measure")

    assert measure_asm is not None
    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" in measure_asm
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in measure_asm


def test_extract_function_asm_surfaces_collection_fast_path_deltas(tmp_path) -> None:
    source = """
fn measure(values: i64[]) -> i64 {
    var total: i64 = 0;
    for value in values {
        total = total + value;
    }
    return total + values[0] + (i64)values.len();
}

fn main() -> i64 {
    var values: i64[] = i64[](2u);
    values[0] = 4;
    values[1] = 6;
    return measure(values);
}
"""

    fast_asm = emit_source_asm(tmp_path, source)
    fallback_asm = emit_source_asm(tmp_path, source, collection_fast_paths_enabled=False)

    fast_measure = extract_function_asm(fast_asm, "measure")
    fallback_measure = extract_function_asm(fallback_asm, "measure")

    assert fast_measure is not None
    assert fallback_measure is not None
    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" not in fast_measure
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in fast_measure
    assert f"    call {ARRAY_LEN_RUNTIME_CALL}" in fallback_measure
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in fallback_measure

    fast_metrics = analyze_assembly_metrics(fast_measure)
    fallback_metrics = analyze_assembly_metrics(fallback_measure)

    assert fast_metrics.line_count != fallback_metrics.line_count


def test_emit_source_asm_keeps_slice_operations_on_runtime_path_when_fast_paths_toggle(tmp_path) -> None:
    source = """
fn measure(values: u64[]) -> u64 {
    var part: u64[] = values.slice_get(0, 2);
    values.slice_set(1, 3, part);
    return 0u;
}

fn main() -> i64 {
    var values: u64[] = u64[](4u);
    values[0] = 10u;
    values[1] = 20u;
    values[2] = 30u;
    values[3] = 40u;
    return (i64)measure(values);
}
"""

    fast_asm = emit_source_asm(tmp_path, source)
    fallback_asm = emit_source_asm(tmp_path, source, collection_fast_paths_enabled=False)

    fast_measure = extract_function_asm(fast_asm, "measure")
    fallback_measure = extract_function_asm(fallback_asm, "measure")

    assert fast_measure is not None
    assert fallback_measure is not None
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in fast_measure
    assert f"    call {ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in fast_measure
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in fallback_measure
    assert f"    call {ARRAY_SLICE_SET_RUNTIME_CALLS[ArrayRuntimeKind.U64]}" in fallback_measure
    assert fast_measure == fallback_measure


def test_emit_source_asm_can_disable_primitive_array_write_fast_paths_for_measurement(tmp_path) -> None:
    source = """
fn measure(values: i64[]) -> i64 {
    var i: i64 = 0;
    var n: i64 = (i64)values.len();
    while i < n {
        values[i] = i + 1;
        i = i + 1;
    }
    return 0;
}

fn main() -> i64 {
    var values: i64[] = i64[](4u);
    return measure(values);
}
"""

    fast_asm = emit_source_asm(tmp_path, source)
    fallback_asm = emit_source_asm(tmp_path, source, collection_fast_paths_enabled=False)

    fast_measure = extract_function_asm(fast_asm, "measure")
    fallback_measure = extract_function_asm(fallback_asm, "measure")

    assert fast_measure is not None
    assert fallback_measure is not None
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in fast_measure
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in fallback_measure


def test_emit_source_asm_can_disable_ref_array_write_fast_paths_for_measurement(tmp_path) -> None:
    source = """
class Box {
    value: i64;
}

fn measure(values: Box[]) -> i64 {
    values[0] = Box(7);
    return values[0].value;
}

fn main() -> i64 {
    var values: Box[] = Box[](1u);
    return measure(values);
}
"""

    fast_asm = emit_source_asm(tmp_path, source)
    fallback_asm = emit_source_asm(tmp_path, source, collection_fast_paths_enabled=False)

    fast_measure = extract_function_asm(fast_asm, "measure")
    fallback_measure = extract_function_asm(fallback_asm, "measure")

    assert fast_measure is not None
    assert fallback_measure is not None
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" not in fast_measure
    assert f"    call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.REF]}" in fallback_measure