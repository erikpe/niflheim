from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_assembly_stats_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "assembly_stats.py"
    spec = importlib.util.spec_from_file_location("assembly_stats_script", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_analyze_assembly_stats_counts_codegen_pressure_categories() -> None:
    module = _load_assembly_stats_module()

    stats = module.analyze_assembly_stats(
        """
.text
main:
    push rbp
    mov rbp, rsp
    sub rsp, 16
    mov qword ptr [rbp - 8], rbx
    mov rax, qword ptr [rbp - 16]
    mov rcx, rax
    add rax, rcx
    cmp rax, 0
    sete al
    jne .Lnext
    call rt_root_slot_store
    mov rbx, qword ptr [rbp - 8]
.Lmain_epilogue:
    mov rbx, qword ptr [rbp - 8]
    pop rbp
    ret
""".strip()
    )

    assert stats.line_count == 18
    assert stats.instruction_count == 15
    assert stats.directive_count == 1
    assert stats.label_count == 2
    assert stats.stack_memory_instruction_count == 4
    assert stats.stack_load_count == 3
    assert stats.stack_store_count == 1
    assert stats.register_copy_count == 2
    assert stats.callee_saved_save_count == 1
    assert stats.callee_saved_restore_count == 1
    assert stats.call_count == 1
    assert stats.conditional_jump_count == 1
    assert stats.compare_count == 1
    assert stats.setcc_count == 1
    assert stats.arithmetic_count == 2
    assert stats.push_pop_count == 2
    assert stats.root_helper_call_count == 1
