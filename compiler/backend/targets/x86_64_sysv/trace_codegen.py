from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.program.symbols import mangle_debug_file_symbol, mangle_debug_function_symbol
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder


@dataclass(frozen=True, slots=True)
class TraceDebugRecord:
    target_label: str
    function_name: str
    file_path: str


def emit_trace_push(builder: X86AsmBuilder, record: TraceDebugRecord, *, line: int, column: int) -> None:
    builder.instruction("lea", "rdi", f"[rip + {mangle_debug_function_symbol(record.target_label)}]")
    builder.instruction("lea", "rsi", f"[rip + {mangle_debug_file_symbol(record.target_label)}]")
    builder.instruction("mov", "edx", str(line))
    builder.instruction("mov", "ecx", str(column))
    builder.instruction("call", "rt_trace_push")


def emit_trace_pop(builder: X86AsmBuilder) -> None:
    builder.instruction("call", "rt_trace_pop")


def emit_trace_location(builder: X86AsmBuilder, *, line: int, column: int) -> None:
    builder.instruction("mov", "edi", str(line))
    builder.instruction("mov", "esi", str(column))
    builder.instruction("call", "rt_trace_set_location")


def emit_trace_debug_literals(builder: X86AsmBuilder, *, records: tuple[TraceDebugRecord, ...]) -> None:
    if not records:
        return
    builder.blank()
    builder.directive(".section .rodata")
    for record in records:
        builder.label(mangle_debug_function_symbol(record.target_label))
        builder.directive(f'.asciz "{_escape_c_string(record.function_name)}"')
        builder.label(mangle_debug_file_symbol(record.target_label))
        builder.directive(f'.asciz "{_escape_c_string(record.file_path)}"')


def _escape_c_string(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
        .replace("\0", "\\0")
    )


__all__ = [
    "TraceDebugRecord",
    "emit_trace_debug_literals",
    "emit_trace_location",
    "emit_trace_pop",
    "emit_trace_push",
]