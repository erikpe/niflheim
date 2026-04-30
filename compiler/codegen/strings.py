from __future__ import annotations

from compiler.common.byte_strings import escape_bytes_for_c_string
from compiler.common.literals import decode_string_literal
import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.walk import walk_codegen_program_expressions
from compiler.semantic.ir import *
from compiler.semantic.lowered_ir import LoweredLinkedSemanticProgram


def escape_asm_string_bytes(data: bytes) -> str:
    return escape_bytes_for_c_string(data)


def escape_c_string(text: str) -> str:
    return escape_asm_string_bytes(text.encode("utf-8"))


def emit_string_literal_section(codegen, program: LoweredLinkedSemanticProgram) -> dict[str, tuple[str, int]]:
    string_literals = collect_string_literals(program)
    labels: dict[str, tuple[str, int]] = {}
    if not string_literals:
        return labels
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for index, literal in enumerate(string_literals):
        label = codegen_symbols.string_literal_symbol(index)
        data = decode_string_literal(literal)
        labels[literal] = (label, len(data))
        codegen.asm.label(label)
        codegen.asm.asciz(escape_asm_string_bytes(data))
    return labels


def collect_string_literals(program: LoweredLinkedSemanticProgram) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    walk_codegen_program_expressions(program, lambda expr: _collect_string_literal(expr, out, seen))
    return out


def _collect_string_literal(expr: SemanticExpr, out: list[str], seen: set[str]) -> None:
    if isinstance(expr, StringLiteralBytesExpr) and expr.literal_text not in seen:
        seen.add(expr.literal_text)
        out.append(expr.literal_text)
