from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.program.symbols import mangle_debug_file_symbol, mangle_debug_function_symbol
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, emit_materialize_symbol_address


@dataclass(frozen=True, slots=True)
class TraceDebugRecord:
    target_label: str
    function_name: str
    file_path: str


def emit_trace_push(builder: AArch64AsmBuilder, record: TraceDebugRecord, *, line: int, column: int) -> None:
    emit_materialize_symbol_address(builder, "x0", mangle_debug_function_symbol(record.target_label))
    emit_materialize_symbol_address(builder, "x1", mangle_debug_file_symbol(record.target_label))
    builder.instruction("mov", "w2", f"#{line}")
    builder.instruction("mov", "w3", f"#{column}")
    builder.instruction("bl", "rt_trace_push")


def emit_trace_pop(builder: AArch64AsmBuilder) -> None:
    builder.instruction("bl", "rt_trace_pop")


def emit_trace_location(builder: AArch64AsmBuilder, *, line: int, column: int) -> None:
    builder.instruction("mov", "w0", f"#{line}")
    builder.instruction("mov", "w1", f"#{column}")
    builder.instruction("bl", "rt_trace_set_location")


def emit_trace_debug_literals(builder: AArch64AsmBuilder, *, records: tuple[TraceDebugRecord, ...]) -> None:
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