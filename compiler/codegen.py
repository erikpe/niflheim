from __future__ import annotations

from dataclasses import dataclass

from compiler.ast_nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CastExpr,
    ExprStmt,
    Expression,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    LiteralExpr,
    ModuleAst,
    NullExpr,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)


@dataclass
class FunctionLayout:
    slot_offsets: dict[str, int]
    stack_size: int


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]


def _epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _offset_operand(offset: int) -> str:
    sign = "+" if offset >= 0 else "-"
    return f"qword ptr [rbp {sign} {abs(offset)}]"


def _collect_locals(stmt: Statement, names: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        names.add(stmt.name)
        return
    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_locals(nested, names)
        return
    if isinstance(stmt, IfStmt):
        _collect_locals(stmt.then_branch, names)
        if stmt.else_branch is not None:
            _collect_locals(stmt.else_branch, names)
        return
    if isinstance(stmt, WhileStmt):
        _collect_locals(stmt.body, names)
        return


def _build_layout(fn: FunctionDecl) -> FunctionLayout:
    ordered_names: list[str] = []
    seen: set[str] = set()

    for param in fn.params:
        if param.name not in seen:
            seen.add(param.name)
            ordered_names.append(param.name)

    local_names: set[str] = set()
    for stmt in fn.body.statements:
        _collect_locals(stmt, local_names)

    for name in sorted(local_names):
        if name not in seen:
            seen.add(name)
            ordered_names.append(name)

    slot_offsets: dict[str, int] = {}
    for index, name in enumerate(ordered_names, start=1):
        slot_offsets[name] = -(8 * index)

    stack_size = _align16(len(ordered_names) * 8)
    return FunctionLayout(slot_offsets=slot_offsets, stack_size=stack_size)


def _emit_bool_normalize(out: list[str]) -> None:
    out.append("    cmp rax, 0")
    out.append("    setne al")
    out.append("    movzx rax, al")


def _next_label(fn_name: str, prefix: str, label_counter: list[int]) -> str:
    value = label_counter[0]
    label_counter[0] += 1
    return f".L{fn_name}_{prefix}_{value}"


def _emit_expr(expr: Expression, layout: FunctionLayout, out: list[str], fn_name: str, label_counter: list[int]) -> None:
    if isinstance(expr, LiteralExpr):
        if expr.value == "true":
            out.append("    mov rax, 1")
            return
        if expr.value == "false":
            out.append("    mov rax, 0")
            return
        if expr.value.isdigit():
            out.append(f"    mov rax, {expr.value}")
            return
        raise NotImplementedError(f"literal codegen not implemented for '{expr.value}'")

    if isinstance(expr, NullExpr):
        out.append("    mov rax, 0")
        return

    if isinstance(expr, IdentifierExpr):
        if expr.name not in layout.slot_offsets:
            raise NotImplementedError(f"identifier '{expr.name}' is not materialized in stack layout")
        out.append(f"    mov rax, {_offset_operand(layout.slot_offsets[expr.name])}")
        return

    if isinstance(expr, CastExpr):
        _emit_expr(expr.operand, layout, out, fn_name, label_counter)
        return

    if isinstance(expr, UnaryExpr):
        _emit_expr(expr.operand, layout, out, fn_name, label_counter)
        if expr.operator == "-":
            out.append("    neg rax")
            return
        if expr.operator == "!":
            _emit_bool_normalize(out)
            out.append("    xor rax, 1")
            return
        raise NotImplementedError(f"unary operator '{expr.operator}' is not supported")

    if isinstance(expr, BinaryExpr):
        if expr.operator in ("&&", "||"):
            branch_id = label_counter[0]
            label_counter[0] += 1
            rhs_label = f".L{fn_name}_logic_rhs_{branch_id}"
            done_label = f".L{fn_name}_logic_done_{branch_id}"

            _emit_expr(expr.left, layout, out, fn_name, label_counter)
            _emit_bool_normalize(out)
            out.append("    cmp rax, 0")
            if expr.operator == "&&":
                out.append(f"    jne {rhs_label}")
                out.append("    mov rax, 0")
            else:
                out.append(f"    je {rhs_label}")
                out.append("    mov rax, 1")
            out.append(f"    jmp {done_label}")
            out.append(f"{rhs_label}:")
            _emit_expr(expr.right, layout, out, fn_name, label_counter)
            _emit_bool_normalize(out)
            out.append(f"{done_label}:")
            return

        _emit_expr(expr.left, layout, out, fn_name, label_counter)
        out.append("    push rax")
        _emit_expr(expr.right, layout, out, fn_name, label_counter)
        out.append("    mov rcx, rax")
        out.append("    pop rax")

        if expr.operator == "+":
            out.append("    add rax, rcx")
            return
        if expr.operator == "-":
            out.append("    sub rax, rcx")
            return
        if expr.operator == "*":
            out.append("    imul rax, rcx")
            return
        if expr.operator == "/":
            out.append("    cqo")
            out.append("    idiv rcx")
            return
        if expr.operator == "%":
            out.append("    cqo")
            out.append("    idiv rcx")
            out.append("    mov rax, rdx")
            return

        if expr.operator in ("==", "!=", "<", "<=", ">", ">="):
            out.append("    cmp rax, rcx")
            if expr.operator == "==":
                out.append("    sete al")
            elif expr.operator == "!=":
                out.append("    setne al")
            elif expr.operator == "<":
                out.append("    setl al")
            elif expr.operator == "<=":
                out.append("    setle al")
            elif expr.operator == ">":
                out.append("    setg al")
            else:
                out.append("    setge al")
            out.append("    movzx rax, al")
            return

        raise NotImplementedError(f"binary operator '{expr.operator}' is not supported")

    raise NotImplementedError(f"expression codegen not implemented for {type(expr).__name__}")


def _emit_statement(
    stmt: Statement,
    epilogue_label: str,
    out: list[str],
    layout: FunctionLayout,
    fn_name: str,
    label_counter: list[int],
) -> None:
    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _emit_expr(stmt.value, layout, out, fn_name, label_counter)
        out.append(f"    jmp {epilogue_label}")
        return

    if isinstance(stmt, VarDeclStmt):
        offset = layout.slot_offsets.get(stmt.name)
        if offset is None:
            raise NotImplementedError(f"variable '{stmt.name}' is not materialized in stack layout")

        if stmt.initializer is None:
            out.append("    mov rax, 0")
        else:
            _emit_expr(stmt.initializer, layout, out, fn_name, label_counter)
        out.append(f"    mov {_offset_operand(offset)}, rax")
        return

    if isinstance(stmt, AssignStmt):
        if not isinstance(stmt.target, IdentifierExpr):
            raise NotImplementedError("assignment codegen currently supports identifier targets only")
        offset = layout.slot_offsets.get(stmt.target.name)
        if offset is None:
            raise NotImplementedError(f"identifier '{stmt.target.name}' is not materialized in stack layout")
        _emit_expr(stmt.value, layout, out, fn_name, label_counter)
        out.append(f"    mov {_offset_operand(offset)}, rax")
        return

    if isinstance(stmt, ExprStmt):
        _emit_expr(stmt.expression, layout, out, fn_name, label_counter)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _emit_statement(nested, epilogue_label, out, layout, fn_name, label_counter)
        return

    if isinstance(stmt, IfStmt):
        else_label = _next_label(fn_name, "if_else", label_counter)
        end_label = _next_label(fn_name, "if_end", label_counter)

        _emit_expr(stmt.condition, layout, out, fn_name, label_counter)
        out.append("    cmp rax, 0")
        out.append(f"    je {else_label}")
        _emit_statement(stmt.then_branch, epilogue_label, out, layout, fn_name, label_counter)
        out.append(f"    jmp {end_label}")
        out.append(f"{else_label}:")
        if stmt.else_branch is not None:
            _emit_statement(stmt.else_branch, epilogue_label, out, layout, fn_name, label_counter)
        out.append(f"{end_label}:")
        return

    if isinstance(stmt, WhileStmt):
        start_label = _next_label(fn_name, "while_start", label_counter)
        end_label = _next_label(fn_name, "while_end", label_counter)

        out.append(f"{start_label}:")
        _emit_expr(stmt.condition, layout, out, fn_name, label_counter)
        out.append("    cmp rax, 0")
        out.append(f"    je {end_label}")
        _emit_statement(stmt.body, epilogue_label, out, layout, fn_name, label_counter)
        out.append(f"    jmp {start_label}")
        out.append(f"{end_label}:")
        return

    raise NotImplementedError(f"statement codegen not implemented for {type(stmt).__name__}")


def _emit_function(fn: FunctionDecl, out: list[str]) -> None:
    label = fn.name
    epilogue = _epilogue_label(fn.name)
    layout = _build_layout(fn)
    label_counter = [0]

    if fn.is_export:
        out.append(f".globl {label}")
    out.append(f"{label}:")
    out.append("    push rbp")
    out.append("    mov rbp, rsp")
    if layout.stack_size > 0:
        out.append(f"    sub rsp, {layout.stack_size}")

    for index, param in enumerate(fn.params):
        if index >= len(PARAM_REGISTERS):
            raise NotImplementedError("parameter codegen currently supports up to 6 SysV integer/pointer params")
        offset = layout.slot_offsets.get(param.name)
        if offset is None:
            continue
        out.append(f"    mov {_offset_operand(offset)}, {PARAM_REGISTERS[index]}")

    for stmt in fn.body.statements:
        _emit_statement(stmt, epilogue, out, layout, fn.name, label_counter)

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
