from __future__ import annotations

from compiler.common.literals import decode_string_literal
from compiler.codegen.linker import CodegenProgram
from compiler.codegen.walk import walk_codegen_program_expressions
from compiler.semantic.ir import *


def escape_asm_string_bytes(data: bytes) -> str:
    pieces: list[str] = []
    for byte in data:
        if byte == 0x22:
            pieces.append('\\"')
        elif byte == 0x5C:
            pieces.append("\\\\")
        elif byte == 0x0A:
            pieces.append("\\n")
        elif byte == 0x0D:
            pieces.append("\\r")
        elif byte == 0x09:
            pieces.append("\\t")
        elif 0x20 <= byte <= 0x7E:
            pieces.append(chr(byte))
        else:
            pieces.append(f"\\{byte:03o}")
    return "".join(pieces)


def escape_c_string(text: str) -> str:
    return escape_asm_string_bytes(text.encode("utf-8"))


def emit_string_literal_section(codegen, program: CodegenProgram) -> dict[str, tuple[str, int]]:
    string_literals = collect_string_literals(program)
    labels: dict[str, tuple[str, int]] = {}
    if not string_literals:
        return labels
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for index, literal in enumerate(string_literals):
        label = f"__nif_str_lit_{index}"
        data = decode_string_literal(literal)
        labels[literal] = (label, len(data))
        codegen.asm.label(label)
        codegen.asm.asciz(escape_asm_string_bytes(data))
    return labels


def collect_string_literals(program: CodegenProgram) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    walk_codegen_program_expressions(program, lambda expr: _collect_string_literal(expr, out, seen))
    return out


def _collect_string_literal(expr: SemanticExpr, out: list[str], seen: set[str]) -> None:
    if isinstance(expr, SyntheticExpr) and expr.synthetic_id.kind == "string_literal_bytes":
        if expr.synthetic_id.name not in seen:
            seen.add(expr.synthetic_id.name)
            out.append(expr.synthetic_id.name)
