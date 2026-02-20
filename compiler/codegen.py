from __future__ import annotations

from compiler.ast_nodes import FunctionDecl, ModuleAst, ReturnStmt, Statement


def _epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def _emit_statement(stmt: Statement, epilogue_label: str, out: list[str]) -> None:
    if isinstance(stmt, ReturnStmt):
        out.append(f"    jmp {epilogue_label}")


def _emit_function(fn: FunctionDecl, out: list[str]) -> None:
    label = fn.name
    epilogue = _epilogue_label(fn.name)

    if fn.is_export:
        out.append(f".globl {label}")
    out.append(f"{label}:")
    out.append("    push rbp")
    out.append("    mov rbp, rsp")

    for stmt in fn.body.statements:
        _emit_statement(stmt, epilogue, out)

    out.append(f"{epilogue}:")
    out.append("    mov rsp, rbp")
    out.append("    pop rbp")
    out.append("    ret")


def emit_asm(module_ast: ModuleAst) -> str:
    lines: list[str] = [
        ".intel_syntax noprefix",
        ".text",
    ]

    for fn in module_ast.functions:
        lines.append("")
        _emit_function(fn, lines)

    lines.append("")
    return "\n".join(lines)
