from __future__ import annotations

from compiler.semantic.ir import *


STR_CLASS_NAME = "Str"


def is_str_type_name(type_name: str) -> bool:
    return type_name == STR_CLASS_NAME or type_name.endswith("::Str")


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


def decode_char_literal(lexeme: str) -> int:
    if len(lexeme) < 3 or not lexeme.startswith("'") or not lexeme.endswith("'"):
        raise ValueError(f"invalid char literal lexeme: {lexeme!r}")

    payload = lexeme[1:-1]
    if len(payload) == 1:
        return ord(payload)

    if not payload.startswith("\\"):
        raise ValueError(f"invalid char literal payload: {lexeme!r}")

    if len(payload) == 2:
        esc = payload[1]
        if esc == "n":
            return 0x0A
        if esc == "r":
            return 0x0D
        if esc == "t":
            return 0x09
        if esc == "0":
            return 0x00
        if esc == "\\":
            return 0x5C
        if esc == "'":
            return 0x27
        if esc == '"':
            return 0x22
        raise ValueError(f"unsupported char escape: {lexeme!r}")

    if len(payload) == 4 and payload[1] == "x":
        return int(payload[2:], 16)

    raise ValueError(f"invalid char literal payload: {lexeme!r}")


def emit_string_literal_section(codegen, program: SemanticProgram) -> dict[str, tuple[str, int]]:
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


def collect_string_literals(program: SemanticProgram) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for fn in program.functions:
        if fn.body is not None:
            _collect_string_literals_from_block(fn.body, out, seen)
    for cls in program.classes:
        for field in cls.fields:
            if field.initializer is not None:
                _collect_string_literals_from_expr(field.initializer, out, seen)
        for method in cls.methods:
            _collect_string_literals_from_block(method.body, out, seen)
    return out


def _collect_string_literals_from_block(block: SemanticBlock, out: list[str], seen: set[str]) -> None:
    for stmt in block.statements:
        _collect_string_literals_from_stmt(stmt, out, seen)


def _collect_string_literals_from_stmt(stmt: SemanticStmt, out: list[str], seen: set[str]) -> None:
    if isinstance(stmt, SemanticBlock):
        _collect_string_literals_from_block(stmt, out, seen)
        return
    if isinstance(stmt, SemanticVarDecl):
        if stmt.initializer is not None:
            _collect_string_literals_from_expr(stmt.initializer, out, seen)
        return
    if isinstance(stmt, SemanticAssign):
        _collect_string_literals_from_expr(stmt.value, out, seen)
        return
    if isinstance(stmt, SemanticExprStmt):
        _collect_string_literals_from_expr(stmt.expr, out, seen)
        return
    if isinstance(stmt, SemanticReturn):
        if stmt.value is not None:
            _collect_string_literals_from_expr(stmt.value, out, seen)
        return
    if isinstance(stmt, SemanticIf):
        _collect_string_literals_from_expr(stmt.condition, out, seen)
        _collect_string_literals_from_block(stmt.then_block, out, seen)
        if stmt.else_block is not None:
            _collect_string_literals_from_block(stmt.else_block, out, seen)
        return
    if isinstance(stmt, SemanticWhile):
        _collect_string_literals_from_expr(stmt.condition, out, seen)
        _collect_string_literals_from_block(stmt.body, out, seen)
        return
    if isinstance(stmt, SemanticForIn):
        _collect_string_literals_from_expr(stmt.collection, out, seen)
        _collect_string_literals_from_block(stmt.body, out, seen)


def _collect_string_literals_from_expr(expr: SemanticExpr, out: list[str], seen: set[str]) -> None:
    if isinstance(expr, SyntheticExpr) and expr.synthetic_id.kind == "string_literal_bytes":
        if expr.synthetic_id.name not in seen:
            seen.add(expr.synthetic_id.name)
            out.append(expr.synthetic_id.name)
        return
    if isinstance(expr, CastExprS):
        _collect_string_literals_from_expr(expr.operand, out, seen)
        return
    if isinstance(expr, UnaryExprS):
        _collect_string_literals_from_expr(expr.operand, out, seen)
        return
    if isinstance(expr, BinaryExprS):
        _collect_string_literals_from_expr(expr.left, out, seen)
        _collect_string_literals_from_expr(expr.right, out, seen)
        return
    if isinstance(expr, FieldReadExpr):
        _collect_string_literals_from_expr(expr.receiver, out, seen)
        return
    if isinstance(expr, FunctionCallExpr | StaticMethodCallExpr | ConstructorCallExpr | CallableValueCallExpr):
        args = expr.args if hasattr(expr, "args") else []
        for arg in args:
            _collect_string_literals_from_expr(arg, out, seen)
        if isinstance(expr, CallableValueCallExpr):
            _collect_string_literals_from_expr(expr.callee, out, seen)
        return
    if isinstance(expr, InstanceMethodCallExpr):
        _collect_string_literals_from_expr(expr.receiver, out, seen)
        for arg in expr.args:
            _collect_string_literals_from_expr(arg, out, seen)
        return
    if isinstance(expr, IndexReadExpr):
        _collect_string_literals_from_expr(expr.target, out, seen)
        _collect_string_literals_from_expr(expr.index, out, seen)
        return
    if isinstance(expr, SliceReadExpr):
        _collect_string_literals_from_expr(expr.target, out, seen)
        _collect_string_literals_from_expr(expr.begin, out, seen)
        _collect_string_literals_from_expr(expr.end, out, seen)
        return
