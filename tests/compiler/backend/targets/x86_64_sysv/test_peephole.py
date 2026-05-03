from __future__ import annotations

from compiler.backend.targets.x86_64_sysv.peephole import cleanup_x86_64_sysv_assembly
from tests.compiler.backend.targets.x86_64_sysv.helpers import emit_source_asm


def test_cleanup_x86_64_sysv_assembly_removes_self_moves() -> None:
    assert cleanup_x86_64_sysv_assembly("    mov rbx, rbx\n    ret\n") == "    ret\n"


def test_cleanup_x86_64_sysv_assembly_removes_adjacent_duplicate_register_moves() -> None:
    assert (
        cleanup_x86_64_sysv_assembly("    mov rbx, r12\n    mov rbx, r12\n    ret\n")
        == "    mov rbx, r12\n    ret\n"
    )


def test_cleanup_x86_64_sysv_assembly_removes_immediately_overwritten_register_moves() -> None:
    assert (
        cleanup_x86_64_sysv_assembly("    mov rbx, r12\n    mov rbx, r13\n    ret\n")
        == "    mov rbx, r13\n    ret\n"
    )


def test_cleanup_x86_64_sysv_assembly_does_not_rewrite_across_labels_or_calls() -> None:
    assembly = (
        "    mov rbx, r12\n"
        ".Lnext:\n"
        "    mov rbx, r13\n"
        "    mov r12, r13\n"
        "    call callee\n"
        "    mov r12, r14\n"
    )

    assert cleanup_x86_64_sysv_assembly(assembly) == assembly


def test_cleanup_x86_64_sysv_assembly_does_not_rewrite_memory_moves() -> None:
    assembly = (
        "    mov qword ptr [rbp - 8], rbx\n"
        "    mov qword ptr [rbp - 8], rbx\n"
        "    mov rbx, qword ptr [rbp - 8]\n"
        "    mov rbx, qword ptr [rbp - 16]\n"
    )

    assert cleanup_x86_64_sysv_assembly(assembly) == assembly


def test_emit_source_asm_runs_peephole_cleanup(tmp_path) -> None:
    asm = emit_source_asm(
        tmp_path,
        """
        fn main() -> i64 {
            var value: i64 = 7;
            return value;
        }
        """,
        skip_optimize=True,
    )

    assert "    mov rbx, rbx" not in asm
    assert "    mov r12, r12" not in asm
