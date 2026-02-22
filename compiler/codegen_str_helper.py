from __future__ import annotations

from compiler.ast_nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    IfStmt,
    IndexExpr,
    LiteralExpr,
    ModuleAst,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)


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


def decode_string_literal(lexeme: str) -> bytes:
    if len(lexeme) < 2 or not lexeme.startswith('"') or not lexeme.endswith('"'):
        raise ValueError(f"invalid string literal lexeme: {lexeme!r}")

    payload = lexeme[1:-1]
    out = bytearray()
    index = 0
    while index < len(payload):
        ch = payload[index]
        if ch != "\\":
            out.append(ord(ch))
            index += 1
            continue

        index += 1
        if index >= len(payload):
            raise ValueError("invalid trailing backslash in string literal")

        esc = payload[index]
        if esc == '"':
            out.append(ord('"'))
            index += 1
            continue
        if esc == "\\":
            out.append(ord("\\"))
            index += 1
            continue
        if esc == "n":
            out.append(0x0A)
            index += 1
            continue
        if esc == "r":
            out.append(0x0D)
            index += 1
            continue
        if esc == "t":
            out.append(0x09)
            index += 1
            continue
        if esc == "0":
            out.append(0x00)
            index += 1
            continue
        if esc == "x":
            if index + 2 >= len(payload):
                raise ValueError("invalid \\x escape in string literal")
            hex_text = payload[index + 1 : index + 3]
            out.append(int(hex_text, 16))
            index += 3
            continue

        raise ValueError(f"unsupported string escape \\{esc}")

    return bytes(out)


def collect_string_literals_from_expr(expr: Expression, out: list[str], seen: set[str]) -> None:
    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            if expr.value not in seen:
                seen.add(expr.value)
                out.append(expr.value)
        return

    if isinstance(expr, CastExpr):
        collect_string_literals_from_expr(expr.operand, out, seen)
        return

    if isinstance(expr, UnaryExpr):
        collect_string_literals_from_expr(expr.operand, out, seen)
        return

    if isinstance(expr, BinaryExpr):
        collect_string_literals_from_expr(expr.left, out, seen)
        collect_string_literals_from_expr(expr.right, out, seen)
        return

    if isinstance(expr, CallExpr):
        collect_string_literals_from_expr(expr.callee, out, seen)
        for arg in expr.arguments:
            collect_string_literals_from_expr(arg, out, seen)
        return

    if isinstance(expr, FieldAccessExpr):
        collect_string_literals_from_expr(expr.object_expr, out, seen)
        return

    if isinstance(expr, IndexExpr):
        collect_string_literals_from_expr(expr.object_expr, out, seen)
        collect_string_literals_from_expr(expr.index_expr, out, seen)


def collect_string_literals_from_stmt(stmt: Statement, out: list[str], seen: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            collect_string_literals_from_expr(stmt.initializer, out, seen)
        return

    if isinstance(stmt, AssignStmt):
        collect_string_literals_from_expr(stmt.target, out, seen)
        collect_string_literals_from_expr(stmt.value, out, seen)
        return

    if isinstance(stmt, ExprStmt):
        collect_string_literals_from_expr(stmt.expression, out, seen)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            collect_string_literals_from_expr(stmt.value, out, seen)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            collect_string_literals_from_stmt(nested, out, seen)
        return

    if isinstance(stmt, IfStmt):
        collect_string_literals_from_expr(stmt.condition, out, seen)
        collect_string_literals_from_stmt(stmt.then_branch, out, seen)
        if stmt.else_branch is not None:
            collect_string_literals_from_stmt(stmt.else_branch, out, seen)
        return

    if isinstance(stmt, WhileStmt):
        collect_string_literals_from_expr(stmt.condition, out, seen)
        collect_string_literals_from_stmt(stmt.body, out, seen)


def collect_string_literals(module_ast: ModuleAst) -> list[str]:
    literals: list[str] = []
    seen: set[str] = set()

    for fn in module_ast.functions:
        if fn.body is None:
            continue
        for stmt in fn.body.statements:
            collect_string_literals_from_stmt(stmt, literals, seen)

    for cls in module_ast.classes:
        for method in cls.methods:
            for stmt in method.body.statements:
                collect_string_literals_from_stmt(stmt, literals, seen)

    return literals
