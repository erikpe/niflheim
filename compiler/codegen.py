from __future__ import annotations

import struct
from pathlib import Path

from compiler.ast_nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    ClassDecl,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    FunctionDecl,
    IdentifierExpr,
    IndexExpr,
    IfStmt,
    LiteralExpr,
    MethodDecl,
    ModuleAst,
    NullExpr,
    ParamDecl,
    ReturnStmt,
    Statement,
    TypeRef,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

from compiler.codegen_model import (
    BOX_VALUE_GETTER_RUNTIME_CALLS,
    BUILTIN_CONSTRUCTOR_RUNTIME_CALLS,
    BUILTIN_INDEX_RUNTIME_CALLS,
    BUILTIN_METHOD_RETURN_TYPES,
    BUILTIN_METHOD_RUNTIME_CALLS,
    BUILTIN_RUNTIME_TYPE_SYMBOLS,
    ConstructorLayout,
    EmitContext,
    FLOAT_PARAM_REGISTERS,
    FunctionLayout,
    PARAM_REGISTERS,
    PRIMITIVE_TYPE_NAMES,
    RUNTIME_REF_ARG_INDICES,
    RUNTIME_RETURN_TYPES,
    ResolvedCallTarget,
    TEMP_RUNTIME_ROOT_SLOT_COUNT,
)


def _epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _offset_operand(offset: int) -> str:
    sign = "+" if offset >= 0 else "-"
    return f"qword ptr [rbp {sign} {abs(offset)}]"


def _is_reference_type_name(type_name: str) -> bool:
    return type_name not in PRIMITIVE_TYPE_NAMES


def _is_double_literal_text(text: str) -> bool:
    if "." not in text:
        return False
    try:
        float(text)
    except ValueError:
        return False
    return True


def _double_literal_bits(text: str) -> int:
    packed = struct.pack("<d", float(text))
    return struct.unpack("<Q", packed)[0]


def _collect_locals(stmt: Statement, local_types_by_name: dict[str, str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        local_types_by_name.setdefault(stmt.name, stmt.type_ref.name)
        return
    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_locals(nested, local_types_by_name)
        return
    if isinstance(stmt, IfStmt):
        _collect_locals(stmt.then_branch, local_types_by_name)
        if stmt.else_branch is not None:
            _collect_locals(stmt.else_branch, local_types_by_name)
        return
    if isinstance(stmt, WhileStmt):
        _collect_locals(stmt.body, local_types_by_name)
        return


def _build_layout(fn: FunctionDecl) -> FunctionLayout:
    ordered_slot_names: list[str] = []
    seen_names: set[str] = set()
    local_types_by_name: dict[str, str] = {}

    for param in fn.params:
        if param.name not in seen_names:
            seen_names.add(param.name)
            ordered_slot_names.append(param.name)
            local_types_by_name[param.name] = param.type_ref.name

    for stmt in fn.body.statements:
        _collect_locals(stmt, local_types_by_name)

    for name in sorted(local_types_by_name):
        if name not in seen_names:
            seen_names.add(name)
            ordered_slot_names.append(name)

    slot_offsets: dict[str, int] = {}
    for index, name in enumerate(ordered_slot_names, start=1):
        slot_offsets[name] = -(8 * index)

    root_slot_names = [name for name in ordered_slot_names if _is_reference_type_name(local_types_by_name[name])]
    root_slot_indices = {name: index for index, name in enumerate(root_slot_names)}

    needs_temp_runtime_roots = _function_needs_temp_runtime_roots(fn)
    temp_root_slot_count = TEMP_RUNTIME_ROOT_SLOT_COUNT if needs_temp_runtime_roots else 0
    temp_root_slot_start_index = len(root_slot_names)
    root_slot_count = len(root_slot_names) + temp_root_slot_count

    root_slot_offsets: dict[str, int] = {}
    root_slots_base_offset = -(8 * (len(ordered_slot_names) + root_slot_count)) if root_slot_count > 0 else 0
    for index, name in enumerate(root_slot_names):
        root_slot_offsets[name] = root_slots_base_offset + (8 * index)
    temp_root_slot_offsets = [
        root_slots_base_offset + (8 * (len(root_slot_names) + index))
        for index in range(temp_root_slot_count)
    ]

    bytes_for_value_slots = len(ordered_slot_names) * 8
    bytes_for_root_slots = root_slot_count * 8
    bytes_for_shadow_stack_state = 32 if root_slot_count > 0 else 0

    bytes_for_slots = bytes_for_value_slots + bytes_for_root_slots
    thread_state_offset = -(bytes_for_slots + 8) if root_slot_count > 0 else 0
    root_frame_offset = -(bytes_for_slots + 8 + 24) if root_slot_count > 0 else 0
    stack_size = _align16(bytes_for_slots + bytes_for_shadow_stack_state)
    return FunctionLayout(
        slot_names=ordered_slot_names,
        slot_offsets=slot_offsets,
        slot_type_names=local_types_by_name,
        root_slot_names=root_slot_names,
        root_slot_indices=root_slot_indices,
        root_slot_offsets=root_slot_offsets,
        temp_root_slot_offsets=temp_root_slot_offsets,
        temp_root_slot_start_index=temp_root_slot_start_index,
        root_slot_count=root_slot_count,
        thread_state_offset=thread_state_offset,
        root_frame_offset=root_frame_offset,
        stack_size=stack_size,
    )


def _expr_needs_temp_runtime_roots(expr: Expression) -> bool:
    if isinstance(expr, CallExpr):
        if isinstance(expr.callee, IdentifierExpr) and expr.callee.name in RUNTIME_REF_ARG_INDICES:
            return True
        if isinstance(expr.callee, FieldAccessExpr) and expr.callee.field_name in {
            "len",
            "push",
            "get",
            "set",
        }:
            return True
        if _expr_needs_temp_runtime_roots(expr.callee):
            return True
        return any(_expr_needs_temp_runtime_roots(arg) for arg in expr.arguments)

    if isinstance(expr, CastExpr):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, UnaryExpr):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, BinaryExpr):
        return _expr_needs_temp_runtime_roots(expr.left) or _expr_needs_temp_runtime_roots(expr.right)
    if isinstance(expr, FieldAccessExpr):
        return _expr_needs_temp_runtime_roots(expr.object_expr)
    if isinstance(expr, IndexExpr):
        return _expr_needs_temp_runtime_roots(expr.object_expr) or _expr_needs_temp_runtime_roots(expr.index_expr)
    return False


def _stmt_needs_temp_runtime_roots(stmt: Statement) -> bool:
    if isinstance(stmt, VarDeclStmt):
        return stmt.initializer is not None and _expr_needs_temp_runtime_roots(stmt.initializer)
    if isinstance(stmt, AssignStmt):
        return _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, ExprStmt):
        return _expr_needs_temp_runtime_roots(stmt.expression)
    if isinstance(stmt, ReturnStmt):
        return stmt.value is not None and _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, BlockStmt):
        return any(_stmt_needs_temp_runtime_roots(nested) for nested in stmt.statements)
    if isinstance(stmt, IfStmt):
        condition_has = _expr_needs_temp_runtime_roots(stmt.condition)
        then_has = _stmt_needs_temp_runtime_roots(stmt.then_branch)
        else_has = _stmt_needs_temp_runtime_roots(stmt.else_branch) if stmt.else_branch is not None else False
        return condition_has or then_has or else_has
    if isinstance(stmt, WhileStmt):
        return _expr_needs_temp_runtime_roots(stmt.condition) or _stmt_needs_temp_runtime_roots(stmt.body)
    return False


def _function_needs_temp_runtime_roots(fn: FunctionDecl) -> bool:
    return any(_stmt_needs_temp_runtime_roots(stmt) for stmt in fn.body.statements)


def _next_label(fn_name: str, prefix: str, label_counter: list[int]) -> str:
    value = label_counter[0]
    label_counter[0] += 1
    return f".L{fn_name}_{prefix}_{value}"


def _is_runtime_call_name(name: str) -> bool:
    return name.startswith("rt_")


def _mangle_type_symbol(type_name: str) -> str:
    builtin_symbol = BUILTIN_RUNTIME_TYPE_SYMBOLS.get(type_name)
    if builtin_symbol is not None:
        return builtin_symbol
    safe = type_name.replace(".", "_")
    return f"__nif_type_{safe}"


def _mangle_type_name_symbol(type_name: str) -> str:
    safe = type_name.replace(".", "_")
    return f"__nif_type_name_{safe}"


def _mangle_method_symbol(type_name: str, method_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    safe_method = method_name.replace(".", "_").replace(":", "_")
    return f"__nif_method_{safe_type}_{safe_method}"


def _mangle_constructor_symbol(type_name: str) -> str:
    safe_type = type_name.replace(".", "_").replace(":", "_")
    return f"__nif_ctor_{safe_type}"


def _escape_c_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _decode_string_literal(lexeme: str) -> bytes:
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


def _collect_string_literals_from_expr(expr: Expression, out: list[str], seen: set[str]) -> None:
    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            if expr.value not in seen:
                seen.add(expr.value)
                out.append(expr.value)
        return

    if isinstance(expr, CastExpr):
        _collect_string_literals_from_expr(expr.operand, out, seen)
        return

    if isinstance(expr, UnaryExpr):
        _collect_string_literals_from_expr(expr.operand, out, seen)
        return

    if isinstance(expr, BinaryExpr):
        _collect_string_literals_from_expr(expr.left, out, seen)
        _collect_string_literals_from_expr(expr.right, out, seen)
        return

    if isinstance(expr, CallExpr):
        _collect_string_literals_from_expr(expr.callee, out, seen)
        for arg in expr.arguments:
            _collect_string_literals_from_expr(arg, out, seen)
        return

    if isinstance(expr, FieldAccessExpr):
        _collect_string_literals_from_expr(expr.object_expr, out, seen)
        return

    if isinstance(expr, IndexExpr):
        _collect_string_literals_from_expr(expr.object_expr, out, seen)
        _collect_string_literals_from_expr(expr.index_expr, out, seen)


def _collect_string_literals_from_stmt(stmt: Statement, out: list[str], seen: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            _collect_string_literals_from_expr(stmt.initializer, out, seen)
        return

    if isinstance(stmt, AssignStmt):
        _collect_string_literals_from_expr(stmt.target, out, seen)
        _collect_string_literals_from_expr(stmt.value, out, seen)
        return

    if isinstance(stmt, ExprStmt):
        _collect_string_literals_from_expr(stmt.expression, out, seen)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_string_literals_from_expr(stmt.value, out, seen)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_string_literals_from_stmt(nested, out, seen)
        return

    if isinstance(stmt, IfStmt):
        _collect_string_literals_from_expr(stmt.condition, out, seen)
        _collect_string_literals_from_stmt(stmt.then_branch, out, seen)
        if stmt.else_branch is not None:
            _collect_string_literals_from_stmt(stmt.else_branch, out, seen)
        return

    if isinstance(stmt, WhileStmt):
        _collect_string_literals_from_expr(stmt.condition, out, seen)
        _collect_string_literals_from_stmt(stmt.body, out, seen)


def _collect_string_literals(module_ast: ModuleAst) -> list[str]:
    literals: list[str] = []
    seen: set[str] = set()

    for fn in module_ast.functions:
        if fn.body is None:
            continue
        for stmt in fn.body.statements:
            _collect_string_literals_from_stmt(stmt, literals, seen)

    for cls in module_ast.classes:
        for method in cls.methods:
            for stmt in method.body.statements:
                _collect_string_literals_from_stmt(stmt, literals, seen)

    return literals


def _collect_reference_cast_types_from_expr(expr: Expression, out: set[str]) -> None:
    if isinstance(expr, CastExpr):
        if _is_reference_type_name(expr.type_ref.name):
            out.add(expr.type_ref.name)
        _collect_reference_cast_types_from_expr(expr.operand, out)
        return

    if isinstance(expr, BinaryExpr):
        _collect_reference_cast_types_from_expr(expr.left, out)
        _collect_reference_cast_types_from_expr(expr.right, out)
        return

    if isinstance(expr, UnaryExpr):
        _collect_reference_cast_types_from_expr(expr.operand, out)
        return

    if isinstance(expr, CallExpr):
        _collect_reference_cast_types_from_expr(expr.callee, out)
        for arg in expr.arguments:
            _collect_reference_cast_types_from_expr(arg, out)
        return


def _collect_reference_cast_types_from_stmt(stmt: Statement, out: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            _collect_reference_cast_types_from_expr(stmt.initializer, out)
        return

    if isinstance(stmt, AssignStmt):
        _collect_reference_cast_types_from_expr(stmt.value, out)
        return

    if isinstance(stmt, ExprStmt):
        _collect_reference_cast_types_from_expr(stmt.expression, out)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _collect_reference_cast_types_from_expr(stmt.value, out)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_reference_cast_types_from_stmt(nested, out)
        return

    if isinstance(stmt, IfStmt):
        _collect_reference_cast_types_from_expr(stmt.condition, out)
        _collect_reference_cast_types_from_stmt(stmt.then_branch, out)
        if stmt.else_branch is not None:
            _collect_reference_cast_types_from_stmt(stmt.else_branch, out)
        return

    if isinstance(stmt, WhileStmt):
        _collect_reference_cast_types_from_expr(stmt.condition, out)
        _collect_reference_cast_types_from_stmt(stmt.body, out)
        return


def _collect_reference_cast_types(module_ast: ModuleAst) -> list[str]:
    names: set[str] = set()
    for cls in module_ast.classes:
        names.add(cls.name)
    for fn in module_ast.functions:
        if fn.body is None:
            continue
        for stmt in fn.body.statements:
            _collect_reference_cast_types_from_stmt(stmt, names)
    for cls in module_ast.classes:
        for method in cls.methods:
            for stmt in method.body.statements:
                _collect_reference_cast_types_from_stmt(stmt, names)
    return sorted(names)


def _flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]

    if isinstance(expr, FieldAccessExpr):
        left = _flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]

    return None


def _resolve_method_call_target(
    callee: FieldAccessExpr,
    ctx: EmitContext,
) -> ResolvedCallTarget:
    receiver_expr = callee.object_expr
    if not isinstance(receiver_expr, IdentifierExpr):
        raise NotImplementedError("method-call codegen currently requires identifier receivers")

    receiver_type_name = ctx.layout.slot_type_names.get(receiver_expr.name)
    if receiver_type_name is None:
        raise NotImplementedError(f"method receiver '{receiver_expr.name}' is not materialized in stack layout")

    method_name = callee.field_name

    builtin_method = BUILTIN_METHOD_RUNTIME_CALLS.get((receiver_type_name, method_name))
    if builtin_method is not None:
        return ResolvedCallTarget(
            name=builtin_method,
            receiver_expr=receiver_expr,
            return_type_name=BUILTIN_METHOD_RETURN_TYPES[(receiver_type_name, method_name)],
        )

    method_label = ctx.method_labels.get((receiver_type_name, method_name))
    if method_label is None and "::" in receiver_type_name:
        unqualified_type_name = receiver_type_name.split("::", 1)[1]
        method_label = ctx.method_labels.get((unqualified_type_name, method_name))
    if method_label is None:
        raise NotImplementedError(f"method-call codegen could not resolve '{receiver_type_name}.{method_name}'")

    return ResolvedCallTarget(
        name=method_label,
        receiver_expr=receiver_expr,
        return_type_name=ctx.method_return_types.get((receiver_type_name, method_name), "i64"),
    )


def _resolve_call_target_name(
    callee: Expression,
    ctx: EmitContext,
) -> ResolvedCallTarget:
    if isinstance(callee, IdentifierExpr):
        builtin_ctor_runtime = BUILTIN_CONSTRUCTOR_RUNTIME_CALLS.get(callee.name)
        if builtin_ctor_runtime is not None:
            return ResolvedCallTarget(name=builtin_ctor_runtime, receiver_expr=None, return_type_name=callee.name)
        ctor_label = ctx.constructor_labels.get(callee.name)
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None, return_type_name=callee.name)
        return ResolvedCallTarget(
            name=callee.name,
            receiver_expr=None,
            return_type_name=ctx.function_return_types.get(callee.name, RUNTIME_RETURN_TYPES.get(callee.name, "i64")),
        )

    if isinstance(callee, FieldAccessExpr):
        chain = _flatten_field_chain(callee)
        if chain is None or len(chain) < 2:
            raise NotImplementedError("call codegen currently supports direct or module-qualified callees only")
        if chain[0] in ctx.layout.slot_offsets:
            return _resolve_method_call_target(callee, ctx)
        ctor_label = ctx.constructor_labels.get(chain[-1])
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None, return_type_name=chain[-1])
        return ResolvedCallTarget(
            name=chain[-1],
            receiver_expr=None,
            return_type_name=ctx.function_return_types.get(chain[-1], RUNTIME_RETURN_TYPES.get(chain[-1], "i64")),
        )

    raise NotImplementedError("call codegen currently supports direct or module-qualified callees only")


def _infer_expression_type_name(
    expr: Expression,
    ctx: EmitContext,
) -> str:
    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            return "Str"
        if expr.value in {"true", "false"}:
            return "bool"
        if _is_double_literal_text(expr.value):
            return "double"
        if expr.value.endswith("u") and expr.value[:-1].isdigit():
            return "u64"
        return "i64"

    if isinstance(expr, NullExpr):
        return "null"

    if isinstance(expr, IdentifierExpr):
        return ctx.layout.slot_type_names.get(expr.name, "i64")

    if isinstance(expr, CastExpr):
        return expr.type_ref.name

    if isinstance(expr, FieldAccessExpr):
        if expr.field_name == "value":
            if isinstance(expr.object_expr, IdentifierExpr):
                receiver_type = ctx.layout.slot_type_names.get(expr.object_expr.name, "Obj")
            elif isinstance(expr.object_expr, CastExpr):
                receiver_type = expr.object_expr.type_ref.name
            else:
                receiver_type = "Obj"
            if receiver_type == "BoxDouble":
                return "double"
            if receiver_type == "BoxU64":
                return "u64"
            if receiver_type == "BoxU8":
                return "u8"
            if receiver_type == "BoxBool":
                return "bool"
            return "i64"
        return "i64"

    if isinstance(expr, IndexExpr):
        if isinstance(expr.object_expr, IdentifierExpr):
            receiver_type = ctx.layout.slot_type_names.get(expr.object_expr.name, "Obj")
            if receiver_type == "Str":
                return "u8"
            if receiver_type == "Vec":
                return "Obj"
        return "i64"

    if isinstance(expr, CallExpr):
        resolved_target = _resolve_call_target_name(expr.callee, ctx)
        return resolved_target.return_type_name

    if isinstance(expr, UnaryExpr):
        if expr.operator == "!":
            return "bool"
        return _infer_expression_type_name(expr.operand, ctx)

    if isinstance(expr, BinaryExpr):
        if expr.operator in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
            return "bool"
        return _infer_expression_type_name(expr.left, ctx)

    return "i64"


def _method_function_decl(class_decl: ClassDecl, method_decl: MethodDecl, label: str) -> FunctionDecl:
    receiver_param = ParamDecl(
        name="__self",
        type_ref=TypeRef(name=class_decl.name, span=method_decl.span),
        span=method_decl.span,
    )
    return FunctionDecl(
        name=label,
        params=[receiver_param, *method_decl.params],
        return_type=method_decl.return_type,
        body=method_decl.body,
        is_export=False,
        is_extern=False,
        span=method_decl.span,
    )


def _constructor_function_decl(class_decl: ClassDecl, label: str) -> FunctionDecl:
    params = [
        ParamDecl(name=field.name, type_ref=field.type_ref, span=field.span)
        for field in class_decl.fields
    ]
    return FunctionDecl(
        name=label,
        params=params,
        return_type=TypeRef(name=class_decl.name, span=class_decl.span),
        body=BlockStmt(statements=[], span=class_decl.span),
        is_export=False,
        is_extern=False,
        span=class_decl.span,
    )


class CodeGenerator:
    def __init__(self, module_ast: ModuleAst) -> None:
        self.module_ast = module_ast
        self.out: list[str] = [".intel_syntax noprefix"]
        self.method_labels: dict[tuple[str, str], str] = {}
        self.method_return_types: dict[tuple[str, str], str] = {}
        self.function_return_types: dict[str, str] = {}
        self.constructor_layouts: dict[str, ConstructorLayout] = {}
        self.constructor_labels: dict[str, str] = {}
        self.string_literal_labels: dict[str, tuple[str, int]] = {}
        self.source_lines_by_path: dict[str, list[str] | None] = {}
        self.last_emitted_comment_location: tuple[str, int] | None = None

    def _source_line_text(self, file_path: str, line: int) -> str:
        if line <= 0:
            return ""
        lines = self.source_lines_by_path.get(file_path)
        if lines is None and file_path not in self.source_lines_by_path:
            try:
                lines = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                lines = None
            self.source_lines_by_path[file_path] = lines
        if lines is None or line > len(lines):
            return ""
        return lines[line - 1].strip()

    def _emit_location_comment(self, *, file_path: str, line: int, column: int) -> None:
        location_key = (file_path, line)
        if self.last_emitted_comment_location == location_key:
            return
        source_line = self._source_line_text(file_path, line)
        self.out.append(f"    # {file_path}:{line}:{column} | {source_line}")
        self.last_emitted_comment_location = location_key

    def _build_symbol_tables(self) -> None:
        for cls in self.module_ast.classes:
            for method in cls.methods:
                self.method_labels[(cls.name, method.name)] = _mangle_method_symbol(cls.name, method.name)
                self.method_return_types[(cls.name, method.name)] = method.return_type.name

        for fn in self.module_ast.functions:
            self.function_return_types[fn.name] = fn.return_type.name

        for cls in self.module_ast.classes:
            ctor_label = _mangle_constructor_symbol(cls.name)
            ctor_layout = ConstructorLayout(
                class_name=cls.name,
                label=ctor_label,
                type_symbol=_mangle_type_symbol(cls.name),
                payload_bytes=len(cls.fields) * 8,
                field_names=[field.name for field in cls.fields],
            )
            self.constructor_layouts[cls.name] = ctor_layout
            self.constructor_labels[cls.name] = ctor_label

    def _emit_frame_prologue(self, target_label: str, layout: FunctionLayout, *, global_symbol: bool) -> None:
        if global_symbol:
            self.out.append(f".globl {target_label}")
        self.out.append(f"{target_label}:")
        self.out.append("    push rbp")
        self.out.append("    mov rbp, rsp")
        if layout.stack_size > 0:
            self.out.append(f"    sub rsp, {layout.stack_size}")

    def _emit_zero_slots(self, layout: FunctionLayout) -> None:
        for name in layout.slot_names:
            self.out.append(f"    mov {_offset_operand(layout.slot_offsets[name])}, 0")
        for name in layout.root_slot_names:
            self.out.append(f"    mov {_offset_operand(layout.root_slot_offsets[name])}, 0")
        for offset in layout.temp_root_slot_offsets:
            self.out.append(f"    mov {_offset_operand(offset)}, 0")

    def _emit_param_spills(self, params: list[ParamDecl], layout: FunctionLayout) -> None:
        integer_param_index = 0
        float_param_index = 0
        for param in params:
            offset = layout.slot_offsets.get(param.name)
            if offset is None:
                continue
            if param.type_ref.name == "double":
                if float_param_index >= len(FLOAT_PARAM_REGISTERS):
                    raise NotImplementedError("parameter codegen currently supports up to 8 floating-point params")
                self.out.append(f"    movq {_offset_operand(offset)}, {FLOAT_PARAM_REGISTERS[float_param_index]}")
                float_param_index += 1
            else:
                if integer_param_index >= len(PARAM_REGISTERS):
                    raise NotImplementedError("parameter codegen currently supports up to 6 SysV integer/pointer params")
                self.out.append(f"    mov {_offset_operand(offset)}, {PARAM_REGISTERS[integer_param_index]}")
                integer_param_index += 1

    def _emit_trace_push(self, fn_debug_name_label: str, fn_debug_file_label: str, line: int, column: int) -> None:
        self.out.append(f"    lea rdi, [rip + {fn_debug_name_label}]")
        self.out.append(f"    lea rsi, [rip + {fn_debug_file_label}]")
        self.out.append(f"    mov edx, {line}")
        self.out.append(f"    mov ecx, {column}")
        self.out.append("    call rt_trace_push")

    def _emit_root_frame_setup(self, layout: FunctionLayout, *, root_count: int, first_root_offset: int) -> None:
        self.out.append("    call rt_thread_state")
        self.out.append(f"    mov {_offset_operand(layout.thread_state_offset)}, rax")
        self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        self.out.append(f"    lea rsi, [rbp - {abs(first_root_offset)}]")
        self.out.append(f"    mov edx, {root_count}")
        self.out.append("    call rt_root_frame_init")
        self.out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
        self.out.append(f"    lea rsi, [rbp - {abs(layout.root_frame_offset)}]")
        self.out.append("    call rt_push_roots")

    def _emit_function_epilogue(self, layout: FunctionLayout, return_type_name: str) -> None:
        if return_type_name == "double":
            self.out.append("    sub rsp, 8")
            self.out.append("    movq qword ptr [rsp], xmm0")
        else:
            self.out.append("    push rax")
        if layout.root_slot_count > 0:
            self.out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
            self.out.append("    call rt_pop_roots")
        self.out.append("    call rt_trace_pop")
        if return_type_name == "double":
            self.out.append("    movq xmm0, qword ptr [rsp]")
            self.out.append("    add rsp, 8")
        else:
            self.out.append("    pop rax")
        self.out.append("    mov rsp, rbp")
        self.out.append("    pop rbp")
        self.out.append("    ret")

    def _emit_ref_epilogue(self, layout: FunctionLayout) -> None:
        self.out.append("    push rax")
        if layout.root_slot_names:
            self.out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
            self.out.append("    call rt_pop_roots")
        self.out.append("    call rt_trace_pop")
        self.out.append("    pop rax")
        self.out.append("    mov rsp, rbp")
        self.out.append("    pop rbp")
        self.out.append("    ret")

    def _emit_runtime_call_hook(
        self,
        *,
        fn_name: str,
        phase: str,
        label_counter: list[int],
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        label = _next_label(fn_name, f"rt_safepoint_{phase}", label_counter)
        self.out.append(f"{label}:")
        self.out.append("    # runtime safepoint hook")
        if phase == "before" and line is not None and column is not None:
            self.out.append(f"    mov edi, {line}")
            self.out.append(f"    mov esi, {column}")
            self.out.append("    call rt_trace_set_location")

    def _emit_root_slot_updates(self, layout: FunctionLayout) -> None:
        if not layout.root_slot_names:
            return

        self.out.append("    # spill reference-typed roots to root slots")
        for name in layout.root_slot_names:
            value_offset = layout.slot_offsets[name]
            slot_index = layout.root_slot_indices[name]
            self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            self.out.append(f"    mov rdx, {_offset_operand(value_offset)}")
            self.out.append(f"    mov esi, {slot_index}")
            self.out.append("    call rt_root_slot_store")

    def _emit_runtime_call_arg_temp_roots(
        self,
        layout: FunctionLayout,
        target_name: str,
        arg_count: int,
    ) -> int:
        if layout.root_slot_count <= 0:
            return 0
        ref_indices = [index for index in RUNTIME_REF_ARG_INDICES.get(target_name, ()) if index < arg_count]
        if not ref_indices:
            return 0
        if len(ref_indices) > len(layout.temp_root_slot_offsets):
            raise NotImplementedError("insufficient temporary root slots for runtime call argument rooting")

        for temp_index, arg_index in enumerate(ref_indices):
            self.out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
            if arg_index == 0:
                self.out.append("    mov rdx, qword ptr [rsp]")
            else:
                self.out.append(f"    mov rdx, qword ptr [rsp + {arg_index * 8}]")
            self.out.append(f"    mov esi, {layout.temp_root_slot_start_index + temp_index}")
            self.out.append("    call rt_root_slot_store")
        return len(ref_indices)

    def _emit_clear_runtime_call_arg_temp_roots(self, layout: FunctionLayout, rooted_count: int) -> None:
        for temp_index in range(rooted_count):
            self.out.append(f"    mov {_offset_operand(layout.temp_root_slot_offsets[temp_index])}, 0")

    def _emit_bool_normalize(self) -> None:
        self.out.append("    cmp rax, 0")
        self.out.append("    setne al")
        self.out.append("    movzx rax, al")

    def _emit_literal_expr(self, expr: LiteralExpr, ctx: EmitContext) -> None:
        layout = ctx.layout
        label_counter = ctx.label_counter
        string_literal_labels = ctx.string_literal_labels

        if expr.value.startswith('"'):
            label_and_len = string_literal_labels.get(expr.value)
            if label_and_len is None:
                raise NotImplementedError("missing string literal lowering metadata")
            data_label, data_len = label_and_len
            self._emit_runtime_call_hook(
                fn_name=ctx.fn_name,
                phase="before",
                label_counter=label_counter,
                line=expr.span.start.line,
                column=expr.span.start.column,
            )
            self._emit_root_slot_updates(layout)
            self.out.append("    call rt_thread_state")
            self.out.append("    mov rdi, rax")
            self.out.append(f"    lea rsi, [rip + {data_label}]")
            self.out.append(f"    mov rdx, {data_len}")
            self.out.append("    call rt_str_from_bytes")
            self._emit_runtime_call_hook(
                fn_name=ctx.fn_name,
                phase="after",
                label_counter=label_counter,
            )
            return

        if expr.value == "true":
            self.out.append("    mov rax, 1")
            return
        if expr.value == "false":
            self.out.append("    mov rax, 0")
            return
        if _is_double_literal_text(expr.value):
            self.out.append(f"    mov rax, 0x{_double_literal_bits(expr.value):016x}")
            return
        if expr.value.isdigit():
            self.out.append(f"    mov rax, {expr.value}")
            return
        if expr.value.endswith("u") and expr.value[:-1].isdigit():
            self.out.append(f"    mov rax, {expr.value[:-1]}")
            return

        raise NotImplementedError(f"literal codegen not implemented for '{expr.value}'")

    def _emit_field_access_expr(self, expr: FieldAccessExpr, ctx: EmitContext) -> None:
        layout = ctx.layout
        label_counter = ctx.label_counter

        receiver_type_name: str | None = None
        if isinstance(expr.object_expr, IdentifierExpr):
            receiver_name = expr.object_expr.name
            receiver_type_name = layout.slot_type_names.get(receiver_name)
            if receiver_type_name is None:
                raise NotImplementedError(f"field receiver '{receiver_name}' is not materialized in stack layout")
        elif isinstance(expr.object_expr, CastExpr):
            receiver_type_name = expr.object_expr.type_ref.name
        else:
            raise NotImplementedError("field access codegen currently supports identifier or cast receivers")

        if expr.field_name == "value":
            getter_name = BOX_VALUE_GETTER_RUNTIME_CALLS.get(receiver_type_name)
            if getter_name is not None:
                self._emit_expr(expr.object_expr, ctx)
                self.out.append("    push rax")
                self._emit_runtime_call_hook(
                    fn_name=ctx.fn_name,
                    phase="before",
                    label_counter=label_counter,
                    line=expr.span.start.line,
                    column=expr.span.start.column,
                )
                self._emit_root_slot_updates(layout)
                self.out.append("    pop rdi")
                self.out.append(f"    call {getter_name}")
                if receiver_type_name == "BoxDouble":
                    self.out.append("    movq rax, xmm0")
                self._emit_runtime_call_hook(
                    fn_name=ctx.fn_name,
                    phase="after",
                    label_counter=label_counter,
                )
                return

        raise NotImplementedError("field access codegen currently supports only Box*.value reads")

    def _emit_cast_expr(self, expr: CastExpr, ctx: EmitContext) -> None:
        label_counter = ctx.label_counter

        self._emit_expr(expr.operand, ctx)
        source_type = _infer_expression_type_name(expr.operand, ctx)
        target_type = expr.type_ref.name
        if _is_reference_type_name(target_type):
            type_symbol = _mangle_type_symbol(target_type)
            self.out.append("    push rax")
            self._emit_runtime_call_hook(
                fn_name=ctx.fn_name,
                phase="before",
                label_counter=label_counter,
                line=expr.span.start.line,
                column=expr.span.start.column,
            )
            self.out.append("    pop rax")
            self.out.append("    mov rdi, rax")
            self.out.append(f"    lea rsi, [rip + {type_symbol}]")
            self.out.append("    call rt_checked_cast")
            self._emit_runtime_call_hook(
                fn_name=ctx.fn_name,
                phase="after",
                label_counter=label_counter,
            )
            return

        if target_type == source_type:
            return

        if target_type == "double" and source_type in {"i64", "u64", "u8", "bool"}:
            self.out.append("    cvtsi2sd xmm0, rax")
            self.out.append("    movq rax, xmm0")
            return

        if source_type == "double" and target_type in {"i64", "u64", "u8", "bool"}:
            self.out.append("    movq xmm0, rax")
            self.out.append("    cvttsd2si rax, xmm0")
            if target_type == "u8":
                self.out.append("    and rax, 255")
            elif target_type == "bool":
                self._emit_bool_normalize()
            return

        if target_type == "u8":
            self.out.append("    and rax, 255")
            return

        if target_type == "bool":
            self._emit_bool_normalize()

    def _emit_index_expr(self, expr: IndexExpr, ctx: EmitContext) -> None:
        layout = ctx.layout
        label_counter = ctx.label_counter

        if not isinstance(expr.object_expr, IdentifierExpr):
            raise NotImplementedError("index codegen currently requires identifier receivers")

        receiver_name = expr.object_expr.name
        receiver_type_name = layout.slot_type_names.get(receiver_name)
        if receiver_type_name is None:
            raise NotImplementedError(f"index receiver '{receiver_name}' is not materialized in stack layout")

        self._emit_expr(expr.index_expr, ctx)
        self.out.append("    push rax")
        self._emit_expr(expr.object_expr, ctx)
        self.out.append("    push rax")

        self._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="before",
            label_counter=label_counter,
            line=expr.span.start.line,
            column=expr.span.start.column,
        )
        self._emit_root_slot_updates(layout)
        self.out.append("    pop rdi")
        self.out.append("    pop rsi")

        runtime_call = BUILTIN_INDEX_RUNTIME_CALLS.get(receiver_type_name)
        if runtime_call is None:
            raise NotImplementedError("index codegen currently supports Str and Vec receivers")
        self.out.append(f"    call {runtime_call}")

        self._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="after",
            label_counter=label_counter,
        )

    def _emit_expr(self, expr: Expression, ctx: EmitContext) -> None:
        layout = ctx.layout

        if isinstance(expr, LiteralExpr):
            self._emit_literal_expr(expr, ctx)
            return

        if isinstance(expr, NullExpr):
            self.out.append("    mov rax, 0")
            return

        if isinstance(expr, IdentifierExpr):
            if expr.name not in layout.slot_offsets:
                raise NotImplementedError(f"identifier '{expr.name}' is not materialized in stack layout")
            self.out.append(f"    mov rax, {_offset_operand(layout.slot_offsets[expr.name])}")
            return

        if isinstance(expr, FieldAccessExpr):
            self._emit_field_access_expr(expr, ctx)
            return

        if isinstance(expr, CastExpr):
            self._emit_cast_expr(expr, ctx)
            return

        if isinstance(expr, IndexExpr):
            self._emit_index_expr(expr, ctx)
            return

        if isinstance(expr, CallExpr):
            self._emit_call_expr(expr, ctx)
            return

        if isinstance(expr, UnaryExpr):
            self._emit_unary_expr(expr, ctx)
            return

        if isinstance(expr, BinaryExpr):
            self._emit_binary_expr(expr, ctx)
            return

        raise NotImplementedError(f"expression codegen not implemented for {type(expr).__name__}")

    def _emit_call_expr(self, expr: CallExpr, ctx: EmitContext) -> None:
        layout = ctx.layout
        fn_name = ctx.fn_name
        label_counter = ctx.label_counter

        resolved_target = _resolve_call_target_name(expr.callee, ctx)
        target_name = resolved_target.name

        call_arguments = list(expr.arguments)
        if resolved_target.receiver_expr is not None:
            call_arguments = [resolved_target.receiver_expr, *call_arguments]

        is_runtime_call = _is_runtime_call_name(target_name)
        arg_count = len(call_arguments)
        call_argument_type_names = [_infer_expression_type_name(arg, ctx) for arg in call_arguments]
        integer_arg_count = sum(1 for type_name in call_argument_type_names if type_name != "double")
        float_arg_count = sum(1 for type_name in call_argument_type_names if type_name == "double")
        if integer_arg_count > len(PARAM_REGISTERS):
            raise NotImplementedError("call codegen currently supports up to 6 integer/pointer positional arguments")
        if float_arg_count > len(FLOAT_PARAM_REGISTERS):
            raise NotImplementedError("call codegen currently supports up to 8 floating-point positional arguments")

        if is_runtime_call:
            self._emit_runtime_call_hook(
                fn_name=fn_name,
                phase="before",
                label_counter=label_counter,
                line=expr.span.start.line,
                column=expr.span.start.column,
            )

        for arg in reversed(call_arguments):
            self._emit_expr(arg, ctx)
            self.out.append("    push rax")

        self._emit_root_slot_updates(layout)
        rooted_runtime_arg_count = 0
        if is_runtime_call:
            rooted_runtime_arg_count = self._emit_runtime_call_arg_temp_roots(layout, target_name, arg_count)

        integer_reg_index = 0
        float_reg_index = 0
        for type_name in call_argument_type_names:
            self.out.append("    pop rax")
            if type_name == "double":
                self.out.append(f"    movq {FLOAT_PARAM_REGISTERS[float_reg_index]}, rax")
                float_reg_index += 1
            else:
                self.out.append(f"    mov {PARAM_REGISTERS[integer_reg_index]}, rax")
                integer_reg_index += 1

        self.out.append(f"    call {target_name}")

        if resolved_target.return_type_name == "double":
            self.out.append("    movq rax, xmm0")
        elif resolved_target.return_type_name == "unit":
            self.out.append("    mov rax, 0")

        if rooted_runtime_arg_count > 0:
            self._emit_clear_runtime_call_arg_temp_roots(layout, rooted_runtime_arg_count)

        if is_runtime_call:
            self._emit_runtime_call_hook(
                fn_name=fn_name,
                phase="after",
                label_counter=label_counter,
            )

    def _emit_unary_expr(self, expr: UnaryExpr, ctx: EmitContext) -> None:
        self._emit_expr(expr.operand, ctx)
        if expr.operator == "-":
            operand_type_name = _infer_expression_type_name(expr.operand, ctx)
            if operand_type_name == "double":
                self.out.append("    movq xmm0, rax")
                self.out.append("    xorpd xmm1, xmm1")
                self.out.append("    subsd xmm1, xmm0")
                self.out.append("    movq rax, xmm1")
                return
            self.out.append("    neg rax")
            return
        if expr.operator == "!":
            self._emit_bool_normalize()
            self.out.append("    xor rax, 1")
            return
        raise NotImplementedError(f"unary operator '{expr.operator}' is not supported")

    def _emit_logical_binary_expr(self, expr: BinaryExpr, *, fn_name: str, label_counter: list[int], ctx: EmitContext) -> bool:
        if expr.operator not in ("&&", "||"):
            return False

        branch_id = label_counter[0]
        label_counter[0] += 1
        rhs_label = f".L{fn_name}_logic_rhs_{branch_id}"
        done_label = f".L{fn_name}_logic_done_{branch_id}"

        self._emit_expr(expr.left, ctx)
        self._emit_bool_normalize()
        self.out.append("    cmp rax, 0")
        if expr.operator == "&&":
            self.out.append(f"    jne {rhs_label}")
            self.out.append("    mov rax, 0")
        else:
            self.out.append(f"    je {rhs_label}")
            self.out.append("    mov rax, 1")
        self.out.append(f"    jmp {done_label}")
        self.out.append(f"{rhs_label}:")
        self._emit_expr(expr.right, ctx)
        self._emit_bool_normalize()
        self.out.append(f"{done_label}:")
        return True

    def _emit_double_binary_op(self, operator: str) -> bool:
        if operator == "+":
            self.out.append("    addsd xmm0, xmm1")
            self.out.append("    movq rax, xmm0")
            return True
        if operator == "-":
            self.out.append("    subsd xmm0, xmm1")
            self.out.append("    movq rax, xmm0")
            return True
        if operator == "*":
            self.out.append("    mulsd xmm0, xmm1")
            self.out.append("    movq rax, xmm0")
            return True
        if operator == "/":
            self.out.append("    divsd xmm0, xmm1")
            self.out.append("    movq rax, xmm0")
            return True

        if operator in ("==", "!=", "<", "<=", ">", ">="):
            self.out.append("    ucomisd xmm0, xmm1")
            if operator == "==":
                self.out.append("    sete al")
                self.out.append("    setnp dl")
                self.out.append("    and al, dl")
            elif operator == "!=":
                self.out.append("    setne al")
                self.out.append("    setp dl")
                self.out.append("    or al, dl")
            elif operator == "<":
                self.out.append("    setb al")
                self.out.append("    setnp dl")
                self.out.append("    and al, dl")
            elif operator == "<=":
                self.out.append("    setbe al")
                self.out.append("    setnp dl")
                self.out.append("    and al, dl")
            elif operator == ">":
                self.out.append("    seta al")
                self.out.append("    setnp dl")
                self.out.append("    and al, dl")
            else:
                self.out.append("    setae al")
                self.out.append("    setnp dl")
                self.out.append("    and al, dl")
            self.out.append("    movzx rax, al")
            return True

        return False

    def _emit_integer_binary_op(self, operator: str) -> bool:
        if operator == "+":
            self.out.append("    add rax, rcx")
            return True
        if operator == "-":
            self.out.append("    sub rax, rcx")
            return True
        if operator == "*":
            self.out.append("    imul rax, rcx")
            return True
        if operator == "/":
            self.out.append("    cqo")
            self.out.append("    idiv rcx")
            return True
        if operator == "%":
            self.out.append("    cqo")
            self.out.append("    idiv rcx")
            self.out.append("    mov rax, rdx")
            return True

        if operator in ("==", "!=", "<", "<=", ">", ">="):
            self.out.append("    cmp rax, rcx")
            if operator == "==":
                self.out.append("    sete al")
            elif operator == "!=":
                self.out.append("    setne al")
            elif operator == "<":
                self.out.append("    setl al")
            elif operator == "<=":
                self.out.append("    setle al")
            elif operator == ">":
                self.out.append("    setg al")
            else:
                self.out.append("    setge al")
            self.out.append("    movzx rax, al")
            return True

        return False

    def _emit_binary_expr(self, expr: BinaryExpr, ctx: EmitContext) -> None:
        fn_name = ctx.fn_name
        label_counter = ctx.label_counter

        if self._emit_logical_binary_expr(expr, fn_name=fn_name, label_counter=label_counter, ctx=ctx):
            return

        self._emit_expr(expr.left, ctx)
        self.out.append("    push rax")
        self._emit_expr(expr.right, ctx)
        self.out.append("    mov rcx, rax")
        self.out.append("    pop rax")

        left_type_name = _infer_expression_type_name(expr.left, ctx)
        right_type_name = _infer_expression_type_name(expr.right, ctx)
        is_double_op = left_type_name == "double" and right_type_name == "double"

        if is_double_op:
            self.out.append("    movq xmm1, rcx")
            self.out.append("    movq xmm0, rax")
            if self._emit_double_binary_op(expr.operator):
                return

            raise NotImplementedError(f"binary operator '{expr.operator}' is not supported for double operands")

        if self._emit_integer_binary_op(expr.operator):
            return

        raise NotImplementedError(f"binary operator '{expr.operator}' is not supported")

    def _emit_statement(
        self,
        stmt: Statement,
        epilogue_label: str,
        function_return_type_name: str,
        ctx: EmitContext,
    ) -> None:
        layout = ctx.layout
        fn_name = ctx.fn_name
        label_counter = ctx.label_counter

        self._emit_location_comment(
            file_path=stmt.span.start.path,
            line=stmt.span.start.line,
            column=stmt.span.start.column,
        )

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._emit_expr(stmt.value, ctx)
            if function_return_type_name == "double":
                self.out.append("    movq xmm0, rax")
            self.out.append(f"    jmp {epilogue_label}")
            return

        if isinstance(stmt, VarDeclStmt):
            offset = layout.slot_offsets.get(stmt.name)
            if offset is None:
                raise NotImplementedError(f"variable '{stmt.name}' is not materialized in stack layout")

            if stmt.initializer is None:
                self.out.append("    mov rax, 0")
            else:
                self._emit_expr(stmt.initializer, ctx)
            self.out.append(f"    mov {_offset_operand(offset)}, rax")
            return

        if isinstance(stmt, AssignStmt):
            if not isinstance(stmt.target, IdentifierExpr):
                raise NotImplementedError("assignment codegen currently supports identifier targets only")
            offset = layout.slot_offsets.get(stmt.target.name)
            if offset is None:
                raise NotImplementedError(f"identifier '{stmt.target.name}' is not materialized in stack layout")
            self._emit_expr(stmt.value, ctx)
            self.out.append(f"    mov {_offset_operand(offset)}, rax")
            return

        if isinstance(stmt, ExprStmt):
            self._emit_expr(stmt.expression, ctx)
            return

        if isinstance(stmt, BlockStmt):
            for nested in stmt.statements:
                self._emit_statement(nested, epilogue_label, function_return_type_name, ctx)
            return

        if isinstance(stmt, IfStmt):
            else_label = _next_label(fn_name, "if_else", label_counter)
            end_label = _next_label(fn_name, "if_end", label_counter)

            self._emit_expr(stmt.condition, ctx)
            self.out.append("    cmp rax, 0")
            self.out.append(f"    je {else_label}")
            self._emit_statement(stmt.then_branch, epilogue_label, function_return_type_name, ctx)
            self.out.append(f"    jmp {end_label}")
            self.out.append(f"{else_label}:")
            if stmt.else_branch is not None:
                self._emit_statement(stmt.else_branch, epilogue_label, function_return_type_name, ctx)
            self.out.append(f"{end_label}:")
            return

        if isinstance(stmt, WhileStmt):
            start_label = _next_label(fn_name, "while_start", label_counter)
            end_label = _next_label(fn_name, "while_end", label_counter)

            self.out.append(f"{start_label}:")
            self._emit_expr(stmt.condition, ctx)
            self.out.append("    cmp rax, 0")
            self.out.append(f"    je {end_label}")
            self._emit_statement(stmt.body, epilogue_label, function_return_type_name, ctx)
            self.out.append(f"    jmp {start_label}")
            self.out.append(f"{end_label}:")
            return

        raise NotImplementedError(f"statement codegen not implemented for {type(stmt).__name__}")

    def _emit_debug_symbol_literals(
        self,
        *,
        target_label: str,
        function_name: str,
        file_path: str,
    ) -> tuple[str, str]:
        safe_target = target_label.replace(".", "_").replace(":", "_")
        fn_label = f"__nif_dbg_fn_{safe_target}"
        file_label = f"__nif_dbg_file_{safe_target}"
        self.out.append("")
        self.out.append(".section .rodata")
        self.out.append(f"{fn_label}:")
        self.out.append(f'    .asciz "{_escape_c_string(function_name)}"')
        self.out.append(f"{file_label}:")
        self.out.append(f'    .asciz "{_escape_c_string(file_path)}"')
        self.out.append("")
        self.out.append(".text")
        return fn_label, file_label

    def _emit_function(self, fn: FunctionDecl, *, label: str | None = None) -> None:
        target_label = label if label is not None else fn.name
        epilogue = _epilogue_label(target_label)
        layout = _build_layout(fn)
        label_counter = [0]
        fn_debug_name_label, fn_debug_file_label = self._emit_debug_symbol_literals(
            target_label=target_label,
            function_name=target_label,
            file_path=fn.span.start.path,
        )

        self._emit_frame_prologue(target_label, layout, global_symbol=label is None and (fn.is_export or fn.name == "main"))
        self._emit_location_comment(
            file_path=fn.span.start.path,
            line=fn.span.start.line,
            column=fn.span.start.column,
        )
        self._emit_zero_slots(layout)
        self._emit_param_spills(fn.params, layout)
        self._emit_trace_push(fn_debug_name_label, fn_debug_file_label, fn.span.start.line, fn.span.start.column)

        if layout.root_slot_count > 0:
            if layout.root_slot_names:
                first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
            else:
                first_root_offset = layout.temp_root_slot_offsets[0]
            self._emit_root_frame_setup(
                layout,
                root_count=layout.root_slot_count,
                first_root_offset=first_root_offset,
            )

        emit_ctx = EmitContext(
            layout=layout,
            fn_name=target_label,
            label_counter=label_counter,
            method_labels=self.method_labels,
            method_return_types=self.method_return_types,
            constructor_labels=self.constructor_labels,
            function_return_types=self.function_return_types,
            string_literal_labels=self.string_literal_labels,
        )

        for stmt in fn.body.statements:
            self._emit_statement(stmt, epilogue, fn.return_type.name, emit_ctx)

        self.out.append(f"{epilogue}:")
        self._emit_function_epilogue(layout, fn.return_type.name)

    def _emit_constructor_function(self, cls: ClassDecl) -> None:
        ctor_layout = self.constructor_layouts[cls.name]
        ctor_fn = _constructor_function_decl(cls, ctor_layout.label)
        target_label = ctor_layout.label
        epilogue = _epilogue_label(target_label)
        layout = _build_layout(ctor_fn)
        label_counter = [0]
        fn_debug_name_label, fn_debug_file_label = self._emit_debug_symbol_literals(
            target_label=target_label,
            function_name=target_label,
            file_path=cls.span.start.path,
        )

        self._emit_frame_prologue(target_label, layout, global_symbol=False)
        self._emit_location_comment(
            file_path=cls.span.start.path,
            line=cls.span.start.line,
            column=cls.span.start.column,
        )
        self._emit_zero_slots(layout)
        self._emit_param_spills(ctor_fn.params, layout)
        self._emit_trace_push(fn_debug_name_label, fn_debug_file_label, cls.span.start.line, cls.span.start.column)

        if layout.root_slot_names:
            first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
            self._emit_root_frame_setup(
                layout,
                root_count=len(layout.root_slot_names),
                first_root_offset=first_root_offset,
            )

        self._emit_runtime_call_hook(
            fn_name=target_label,
            phase="before",
            label_counter=label_counter,
        )
        self._emit_root_slot_updates(layout)
        self.out.append("    call rt_thread_state")
        self.out.append("    mov rdi, rax")
        self.out.append(f"    lea rsi, [rip + {ctor_layout.type_symbol}]")
        self.out.append(f"    mov rdx, {ctor_layout.payload_bytes}")
        self.out.append("    call rt_alloc_obj")
        self._emit_runtime_call_hook(
            fn_name=target_label,
            phase="after",
            label_counter=label_counter,
        )

        for field_index, field_name in enumerate(ctor_layout.field_names):
            field_offset = 24 + (8 * field_index)
            value_offset = layout.slot_offsets[field_name]
            self.out.append(f"    mov rcx, {_offset_operand(value_offset)}")
            self.out.append(f"    mov qword ptr [rax + {field_offset}], rcx")

        self.out.append(f"    jmp {epilogue}")

        self.out.append(f"{epilogue}:")
        self._emit_ref_epilogue(layout)

    def _emit_string_literal_section(self) -> dict[str, tuple[str, int]]:
        string_literals = _collect_string_literals(self.module_ast)
        labels: dict[str, tuple[str, int]] = {}
        if not string_literals:
            return labels

        self.out.append("")
        self.out.append(".section .rodata")
        for index, literal in enumerate(string_literals):
            label = f"__nif_str_lit_{index}"
            data = _decode_string_literal(literal)
            labels[literal] = (label, len(data))
            self.out.append(f"{label}:")
            if data:
                data_bytes = ", ".join(str(byte) for byte in data)
                self.out.append(f"    .byte {data_bytes}")
            else:
                self.out.append("    .byte 0")

        return labels

    def _emit_type_metadata_section(self) -> None:
        type_names = _collect_reference_cast_types(self.module_ast)
        if not type_names:
            return

        self.out.append("")
        self.out.append(".section .rodata")
        for type_name in type_names:
            self.out.append(f"{_mangle_type_name_symbol(type_name)}:")
            self.out.append(f'    .asciz "{type_name}"')

        self.out.append("")
        self.out.append(".data")
        for type_name in type_names:
            type_sym = _mangle_type_symbol(type_name)
            name_sym = _mangle_type_name_symbol(type_name)
            self.out.append("    .p2align 3")
            self.out.append(f"{type_sym}:")
            self.out.append("    .long 0")
            self.out.append("    .long 0")
            self.out.append("    .long 1")
            self.out.append("    .long 8")
            self.out.append("    .quad 0")
            self.out.append(f"    .quad {name_sym}")
            self.out.append("    .quad 0")
            self.out.append("    .quad 0")
            self.out.append("    .long 0")
            self.out.append("    .long 0")

    def generate(self) -> str:
        self._emit_type_metadata_section()
        self.string_literal_labels = self._emit_string_literal_section()

        self.out.append("")
        self.out.append(".text")

        self._build_symbol_tables()

        for fn in self.module_ast.functions:
            if fn.is_extern:
                continue
            self.out.append("")
            self._emit_function(fn)

        for cls in self.module_ast.classes:
            for method in cls.methods:
                self.out.append("")
                method_label = self.method_labels[(cls.name, method.name)]
                method_fn = _method_function_decl(cls, method, method_label)
                self._emit_function(method_fn, label=method_label)

        for cls in self.module_ast.classes:
            self.out.append("")
            self._emit_constructor_function(cls)

        self.out.append("")
        self.out.append('.section .note.GNU-stack,"",@progbits')
        self.out.append("")
        return "\n".join(self.out)


def emit_asm(module_ast: ModuleAst) -> str:
    return CodeGenerator(module_ast).generate()
