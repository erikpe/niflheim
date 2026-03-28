from compiler.codegen.measurement import analyze_assembly_metrics, extract_function_asm


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