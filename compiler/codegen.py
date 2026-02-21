from __future__ import annotations

from dataclasses import dataclass

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


@dataclass
class FunctionLayout:
    slot_names: list[str]
    slot_offsets: dict[str, int]
    slot_type_names: dict[str, str]
    root_slot_names: list[str]
    root_slot_indices: dict[str, int]
    root_slot_offsets: dict[str, int]
    thread_state_offset: int
    root_frame_offset: int
    stack_size: int


@dataclass(frozen=True)
class ResolvedCallTarget:
    name: str
    receiver_expr: Expression | None


@dataclass(frozen=True)
class ConstructorLayout:
    class_name: str
    label: str
    type_symbol: str
    payload_bytes: int
    field_names: list[str]


PARAM_REGISTERS = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]
PRIMITIVE_TYPE_NAMES = {"i64", "u64", "u8", "bool", "double", "unit"}
BOX_CONSTRUCTOR_RUNTIME_CALLS = {
    "BoxI64": "rt_box_i64_new",
    "BoxU64": "rt_box_u64_new",
    "BoxU8": "rt_box_u8_new",
    "BoxBool": "rt_box_bool_new",
    "BoxDouble": "rt_box_double_new",
}
BUILTIN_CONSTRUCTOR_RUNTIME_CALLS = {
    "Vec": "rt_vec_new",
    **BOX_CONSTRUCTOR_RUNTIME_CALLS,
}
BOX_VALUE_GETTER_RUNTIME_CALLS = {
    "BoxI64": "rt_box_i64_get",
    "BoxU64": "rt_box_u64_get",
    "BoxU8": "rt_box_u8_get",
    "BoxBool": "rt_box_bool_get",
    "BoxDouble": "rt_box_double_get",
}
BUILTIN_METHOD_RUNTIME_CALLS = {
    ("Vec", "len"): "rt_vec_len",
    ("Vec", "push"): "rt_vec_push",
    ("Vec", "get"): "rt_vec_get",
    ("Vec", "set"): "rt_vec_set",
}


def _epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _offset_operand(offset: int) -> str:
    sign = "+" if offset >= 0 else "-"
    return f"qword ptr [rbp {sign} {abs(offset)}]"


def _is_reference_type_name(type_name: str) -> bool:
    return type_name not in PRIMITIVE_TYPE_NAMES


def _collect_locals(stmt: Statement, types_by_name: dict[str, str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        types_by_name.setdefault(stmt.name, stmt.type_ref.name)
        return
    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_locals(nested, types_by_name)
        return
    if isinstance(stmt, IfStmt):
        _collect_locals(stmt.then_branch, types_by_name)
        if stmt.else_branch is not None:
            _collect_locals(stmt.else_branch, types_by_name)
        return
    if isinstance(stmt, WhileStmt):
        _collect_locals(stmt.body, types_by_name)
        return


def _build_layout(fn: FunctionDecl) -> FunctionLayout:
    ordered_names: list[str] = []
    seen: set[str] = set()
    types_by_name: dict[str, str] = {}

    for param in fn.params:
        if param.name not in seen:
            seen.add(param.name)
            ordered_names.append(param.name)
            types_by_name[param.name] = param.type_ref.name

    for stmt in fn.body.statements:
        _collect_locals(stmt, types_by_name)

    for name in sorted(types_by_name):
        if name not in seen:
            seen.add(name)
            ordered_names.append(name)

    slot_offsets: dict[str, int] = {}
    for index, name in enumerate(ordered_names, start=1):
        slot_offsets[name] = -(8 * index)

    root_slot_names = [name for name in ordered_names if _is_reference_type_name(types_by_name[name])]
    root_slot_indices = {name: index for index, name in enumerate(root_slot_names)}

    root_slot_offsets: dict[str, int] = {}
    for index, name in enumerate(root_slot_names, start=1):
        root_slot_offsets[name] = -(8 * (len(ordered_names) + index))

    bytes_for_value_slots = len(ordered_names) * 8
    bytes_for_root_slots = len(root_slot_names) * 8
    bytes_for_shadow_stack_state = 32 if root_slot_names else 0

    bytes_for_slots = bytes_for_value_slots + bytes_for_root_slots
    thread_state_offset = -(bytes_for_slots + 8) if root_slot_names else 0
    root_frame_offset = -(bytes_for_slots + 8 + 24) if root_slot_names else 0
    stack_size = _align16(bytes_for_slots + bytes_for_shadow_stack_state)
    return FunctionLayout(
        slot_names=ordered_names,
        slot_offsets=slot_offsets,
        slot_type_names=types_by_name,
        root_slot_names=root_slot_names,
        root_slot_indices=root_slot_indices,
        root_slot_offsets=root_slot_offsets,
        thread_state_offset=thread_state_offset,
        root_frame_offset=root_frame_offset,
        stack_size=stack_size,
    )


def _emit_bool_normalize(out: list[str]) -> None:
    out.append("    cmp rax, 0")
    out.append("    setne al")
    out.append("    movzx rax, al")


def _next_label(fn_name: str, prefix: str, label_counter: list[int]) -> str:
    value = label_counter[0]
    label_counter[0] += 1
    return f".L{fn_name}_{prefix}_{value}"


def _is_runtime_call_name(name: str) -> bool:
    return name.startswith("rt_")


def _mangle_type_symbol(type_name: str) -> str:
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


def _emit_string_literal_section(module_ast: ModuleAst, out: list[str]) -> dict[str, tuple[str, int]]:
    string_literals = _collect_string_literals(module_ast)
    labels: dict[str, tuple[str, int]] = {}
    if not string_literals:
        return labels

    out.append("")
    out.append(".section .rodata")
    for index, literal in enumerate(string_literals):
        label = f"__nif_str_lit_{index}"
        data = _decode_string_literal(literal)
        labels[literal] = (label, len(data))
        out.append(f"{label}:")
        if data:
            data_bytes = ", ".join(str(byte) for byte in data)
            out.append(f"    .byte {data_bytes}")
        else:
            out.append("    .byte 0")

    return labels


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


def _emit_type_metadata_section(module_ast: ModuleAst, out: list[str]) -> None:
    type_names = _collect_reference_cast_types(module_ast)
    if not type_names:
        return

    out.append("")
    out.append(".section .rodata")
    for type_name in type_names:
        out.append(f"{_mangle_type_name_symbol(type_name)}:")
        out.append(f'    .asciz "{type_name}"')

    out.append("")
    out.append(".data")
    for type_name in type_names:
        type_sym = _mangle_type_symbol(type_name)
        name_sym = _mangle_type_name_symbol(type_name)
        out.append("    .p2align 3")
        out.append(f"{type_sym}:")
        out.append("    .long 0")
        out.append("    .long 0")
        out.append("    .long 1")
        out.append("    .long 8")
        out.append("    .quad 0")
        out.append(f"    .quad {name_sym}")
        out.append("    .quad 0")
        out.append("    .quad 0")
        out.append("    .long 0")
        out.append("    .long 0")


def _emit_runtime_call_hook(
    *,
    fn_name: str,
    phase: str,
    out: list[str],
    label_counter: list[int],
) -> None:
    label = _next_label(fn_name, f"rt_safepoint_{phase}", label_counter)
    out.append(f"{label}:")
    out.append("    # runtime safepoint hook")


def _emit_root_slot_updates(layout: FunctionLayout, out: list[str]) -> None:
    if not layout.root_slot_names:
        return

    out.append("    # spill reference-typed roots to root slots")
    for name in layout.root_slot_names:
        value_offset = layout.slot_offsets[name]
        slot_index = layout.root_slot_indices[name]
        out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        out.append(f"    mov rdx, {_offset_operand(value_offset)}")
        out.append(f"    mov esi, {slot_index}")
        out.append("    call rt_root_slot_store")


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
    layout: FunctionLayout,
    method_labels: dict[tuple[str, str], str],
) -> ResolvedCallTarget:
    receiver_expr = callee.object_expr
    if not isinstance(receiver_expr, IdentifierExpr):
        raise NotImplementedError("method-call codegen currently requires identifier receivers")

    receiver_type_name = layout.slot_type_names.get(receiver_expr.name)
    if receiver_type_name is None:
        raise NotImplementedError(f"method receiver '{receiver_expr.name}' is not materialized in stack layout")

    method_name = callee.field_name

    builtin_method = BUILTIN_METHOD_RUNTIME_CALLS.get((receiver_type_name, method_name))
    if builtin_method is not None:
        return ResolvedCallTarget(name=builtin_method, receiver_expr=receiver_expr)

    method_label = method_labels.get((receiver_type_name, method_name))
    if method_label is None and "::" in receiver_type_name:
        unqualified_type_name = receiver_type_name.split("::", 1)[1]
        method_label = method_labels.get((unqualified_type_name, method_name))
    if method_label is None:
        raise NotImplementedError(f"method-call codegen could not resolve '{receiver_type_name}.{method_name}'")

    return ResolvedCallTarget(name=method_label, receiver_expr=receiver_expr)


def _resolve_call_target_name(
    callee: Expression,
    layout: FunctionLayout,
    method_labels: dict[tuple[str, str], str],
    constructor_labels: dict[str, str],
) -> ResolvedCallTarget:
    if isinstance(callee, IdentifierExpr):
        builtin_ctor_runtime = BUILTIN_CONSTRUCTOR_RUNTIME_CALLS.get(callee.name)
        if builtin_ctor_runtime is not None:
            return ResolvedCallTarget(name=builtin_ctor_runtime, receiver_expr=None)
        ctor_label = constructor_labels.get(callee.name)
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None)
        return ResolvedCallTarget(name=callee.name, receiver_expr=None)

    if isinstance(callee, FieldAccessExpr):
        chain = _flatten_field_chain(callee)
        if chain is None or len(chain) < 2:
            raise NotImplementedError("call codegen currently supports direct or module-qualified callees only")
        if chain[0] in layout.slot_offsets:
            return _resolve_method_call_target(callee, layout, method_labels)
        ctor_label = constructor_labels.get(chain[-1])
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None)
        return ResolvedCallTarget(name=chain[-1], receiver_expr=None)

    raise NotImplementedError("call codegen currently supports direct or module-qualified callees only")


def _emit_expr(
    expr: Expression,
    layout: FunctionLayout,
    out: list[str],
    fn_name: str,
    label_counter: list[int],
    method_labels: dict[tuple[str, str], str],
    constructor_labels: dict[str, str],
    string_literal_labels: dict[str, tuple[str, int]],
) -> None:
    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            label_and_len = string_literal_labels.get(expr.value)
            if label_and_len is None:
                raise NotImplementedError("missing string literal lowering metadata")
            data_label, data_len = label_and_len
            _emit_runtime_call_hook(
                fn_name=fn_name,
                phase="before",
                out=out,
                label_counter=label_counter,
            )
            _emit_root_slot_updates(layout, out)
            out.append("    call rt_thread_state")
            out.append("    mov rdi, rax")
            out.append(f"    lea rsi, [rip + {data_label}]")
            out.append(f"    mov rdx, {data_len}")
            out.append("    call rt_str_from_bytes")
            _emit_runtime_call_hook(
                fn_name=fn_name,
                phase="after",
                out=out,
                label_counter=label_counter,
            )
            return
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

    if isinstance(expr, FieldAccessExpr):
        if not isinstance(expr.object_expr, IdentifierExpr):
            raise NotImplementedError("field access codegen currently requires identifier receivers")

        receiver_name = expr.object_expr.name
        receiver_type_name = layout.slot_type_names.get(receiver_name)
        if receiver_type_name is None:
            raise NotImplementedError(f"field receiver '{receiver_name}' is not materialized in stack layout")

        if expr.field_name == "value":
            getter_name = BOX_VALUE_GETTER_RUNTIME_CALLS.get(receiver_type_name)
            if getter_name is not None:
                _emit_expr(
                    expr.object_expr,
                    layout,
                    out,
                    fn_name,
                    label_counter,
                    method_labels,
                    constructor_labels,
                    string_literal_labels,
                )
                out.append("    push rax")
                _emit_runtime_call_hook(
                    fn_name=fn_name,
                    phase="before",
                    out=out,
                    label_counter=label_counter,
                )
                _emit_root_slot_updates(layout, out)
                out.append("    pop rdi")
                out.append(f"    call {getter_name}")
                _emit_runtime_call_hook(
                    fn_name=fn_name,
                    phase="after",
                    out=out,
                    label_counter=label_counter,
                )
                return

        raise NotImplementedError("field access codegen currently supports only Box*.value reads")

    if isinstance(expr, CastExpr):
        _emit_expr(
            expr.operand,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        target_type = expr.type_ref.name
        if _is_reference_type_name(target_type):
            type_symbol = _mangle_type_symbol(target_type)
            out.append("    mov rdi, rax")
            out.append(f"    lea rsi, [rip + {type_symbol}]")
            out.append("    call rt_checked_cast")
        return

    if isinstance(expr, IndexExpr):
        if not isinstance(expr.object_expr, IdentifierExpr):
            raise NotImplementedError("index codegen currently requires identifier receivers")

        receiver_name = expr.object_expr.name
        receiver_type_name = layout.slot_type_names.get(receiver_name)
        if receiver_type_name is None:
            raise NotImplementedError(f"index receiver '{receiver_name}' is not materialized in stack layout")

        _emit_expr(
            expr.index_expr,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append("    push rax")
        _emit_expr(
            expr.object_expr,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append("    push rax")

        _emit_runtime_call_hook(
            fn_name=fn_name,
            phase="before",
            out=out,
            label_counter=label_counter,
        )
        _emit_root_slot_updates(layout, out)
        out.append("    pop rdi")
        out.append("    pop rsi")

        if receiver_type_name == "Str":
            out.append("    call rt_str_get_u8")
        elif receiver_type_name == "Vec":
            out.append("    call rt_vec_get")
        else:
            raise NotImplementedError("index codegen currently supports Str and Vec receivers")

        _emit_runtime_call_hook(
            fn_name=fn_name,
            phase="after",
            out=out,
            label_counter=label_counter,
        )
        return

    if isinstance(expr, CallExpr):
        resolved_target = _resolve_call_target_name(expr.callee, layout, method_labels, constructor_labels)
        target_name = resolved_target.name

        call_arguments = list(expr.arguments)
        if resolved_target.receiver_expr is not None:
            call_arguments = [resolved_target.receiver_expr, *call_arguments]

        is_runtime_call = _is_runtime_call_name(target_name)
        arg_count = len(call_arguments)
        if arg_count > len(PARAM_REGISTERS):
            raise NotImplementedError("call codegen currently supports up to 6 positional arguments")

        if is_runtime_call:
            _emit_runtime_call_hook(
                fn_name=fn_name,
                phase="before",
                out=out,
                label_counter=label_counter,
            )

        for arg in reversed(call_arguments):
            _emit_expr(
                arg,
                layout,
                out,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
            out.append("    push rax")

        _emit_root_slot_updates(layout, out)

        for index in range(arg_count):
            out.append(f"    pop {PARAM_REGISTERS[index]}")

        out.append(f"    call {target_name}")

        if is_runtime_call:
            _emit_runtime_call_hook(
                fn_name=fn_name,
                phase="after",
                out=out,
                label_counter=label_counter,
            )
        return

    if isinstance(expr, UnaryExpr):
        _emit_expr(
            expr.operand,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
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

            _emit_expr(
                expr.left,
                layout,
                out,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
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
            _emit_expr(
                expr.right,
                layout,
                out,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
            _emit_bool_normalize(out)
            out.append(f"{done_label}:")
            return

        _emit_expr(
            expr.left,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append("    push rax")
        _emit_expr(
            expr.right,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
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
    method_labels: dict[tuple[str, str], str],
    constructor_labels: dict[str, str],
    string_literal_labels: dict[str, tuple[str, int]],
) -> None:
    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            _emit_expr(
                stmt.value,
                layout,
                out,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
        out.append(f"    jmp {epilogue_label}")
        return

    if isinstance(stmt, VarDeclStmt):
        offset = layout.slot_offsets.get(stmt.name)
        if offset is None:
            raise NotImplementedError(f"variable '{stmt.name}' is not materialized in stack layout")

        if stmt.initializer is None:
            out.append("    mov rax, 0")
        else:
            _emit_expr(
                stmt.initializer,
                layout,
                out,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
        out.append(f"    mov {_offset_operand(offset)}, rax")
        return

    if isinstance(stmt, AssignStmt):
        if not isinstance(stmt.target, IdentifierExpr):
            raise NotImplementedError("assignment codegen currently supports identifier targets only")
        offset = layout.slot_offsets.get(stmt.target.name)
        if offset is None:
            raise NotImplementedError(f"identifier '{stmt.target.name}' is not materialized in stack layout")
        _emit_expr(
            stmt.value,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append(f"    mov {_offset_operand(offset)}, rax")
        return

    if isinstance(stmt, ExprStmt):
        _emit_expr(
            stmt.expression,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _emit_statement(
                nested,
                epilogue_label,
                out,
                layout,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )

        return

    if isinstance(stmt, IfStmt):
        else_label = _next_label(fn_name, "if_else", label_counter)
        end_label = _next_label(fn_name, "if_end", label_counter)

        _emit_expr(
            stmt.condition,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append("    cmp rax, 0")
        out.append(f"    je {else_label}")
        _emit_statement(
            stmt.then_branch,
            epilogue_label,
            out,
            layout,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append(f"    jmp {end_label}")
        out.append(f"{else_label}:")
        if stmt.else_branch is not None:
            _emit_statement(
                stmt.else_branch,
                epilogue_label,
                out,
                layout,
                fn_name,
                label_counter,
                method_labels,
                constructor_labels,
                string_literal_labels,
            )
        out.append(f"{end_label}:")
        return

    if isinstance(stmt, WhileStmt):
        start_label = _next_label(fn_name, "while_start", label_counter)
        end_label = _next_label(fn_name, "while_end", label_counter)

        out.append(f"{start_label}:")
        _emit_expr(
            stmt.condition,
            layout,
            out,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append("    cmp rax, 0")
        out.append(f"    je {end_label}")
        _emit_statement(
            stmt.body,
            epilogue_label,
            out,
            layout,
            fn_name,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )
        out.append(f"    jmp {start_label}")
        out.append(f"{end_label}:")
        return

    raise NotImplementedError(f"statement codegen not implemented for {type(stmt).__name__}")


def _emit_function(
    fn: FunctionDecl,
    out: list[str],
    method_labels: dict[tuple[str, str], str],
    constructor_labels: dict[str, str],
    string_literal_labels: dict[str, tuple[str, int]],
    *,
    label: str | None = None,
) -> None:
    target_label = label if label is not None else fn.name
    epilogue = _epilogue_label(target_label)
    layout = _build_layout(fn)
    label_counter = [0]

    if label is None and (fn.is_export or fn.name == "main"):
        out.append(f".globl {target_label}")
    out.append(f"{target_label}:")
    out.append("    push rbp")
    out.append("    mov rbp, rsp")
    if layout.stack_size > 0:
        out.append(f"    sub rsp, {layout.stack_size}")

    for name in layout.slot_names:
        out.append(f"    mov {_offset_operand(layout.slot_offsets[name])}, 0")
    for name in layout.root_slot_names:
        out.append(f"    mov {_offset_operand(layout.root_slot_offsets[name])}, 0")

    for index, param in enumerate(fn.params):
        if index >= len(PARAM_REGISTERS):
            raise NotImplementedError("parameter codegen currently supports up to 6 SysV integer/pointer params")
        offset = layout.slot_offsets.get(param.name)
        if offset is None:
            continue
        out.append(f"    mov {_offset_operand(offset)}, {PARAM_REGISTERS[index]}")

    if layout.root_slot_names:
        out.append("    call rt_thread_state")
        out.append(f"    mov {_offset_operand(layout.thread_state_offset)}, rax")
        out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        out.append(f"    lea rsi, [rbp - {abs(first_root_offset)}]")
        out.append(f"    mov edx, {len(layout.root_slot_names)}")
        out.append("    call rt_root_frame_init")
        out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
        out.append(f"    lea rsi, [rbp - {abs(layout.root_frame_offset)}]")
        out.append("    call rt_push_roots")

    for stmt in fn.body.statements:
        _emit_statement(
            stmt,
            epilogue,
            out,
            layout,
            target_label,
            label_counter,
            method_labels,
            constructor_labels,
            string_literal_labels,
        )

    out.append(f"{epilogue}:")
    if layout.root_slot_names:
        out.append("    push rax")
        out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
        out.append("    call rt_pop_roots")
        out.append("    pop rax")
    out.append("    mov rsp, rbp")
    out.append("    pop rbp")
    out.append("    ret")


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


def _emit_constructor_function(
    class_decl: ClassDecl,
    ctor_layout: ConstructorLayout,
    out: list[str],
) -> None:
    ctor_fn = _constructor_function_decl(class_decl, ctor_layout.label)
    target_label = ctor_layout.label
    epilogue = _epilogue_label(target_label)
    layout = _build_layout(ctor_fn)
    label_counter = [0]

    out.append(f"{target_label}:")
    out.append("    push rbp")
    out.append("    mov rbp, rsp")
    if layout.stack_size > 0:
        out.append(f"    sub rsp, {layout.stack_size}")

    for name in layout.slot_names:
        out.append(f"    mov {_offset_operand(layout.slot_offsets[name])}, 0")
    for name in layout.root_slot_names:
        out.append(f"    mov {_offset_operand(layout.root_slot_offsets[name])}, 0")

    for index, param in enumerate(ctor_fn.params):
        if index >= len(PARAM_REGISTERS):
            raise NotImplementedError("parameter codegen currently supports up to 6 SysV integer/pointer params")
        offset = layout.slot_offsets.get(param.name)
        if offset is None:
            continue
        out.append(f"    mov {_offset_operand(offset)}, {PARAM_REGISTERS[index]}")

    if layout.root_slot_names:
        out.append("    call rt_thread_state")
        out.append(f"    mov {_offset_operand(layout.thread_state_offset)}, rax")
        out.append(f"    lea rdi, [rbp - {abs(layout.root_frame_offset)}]")
        first_root_offset = layout.root_slot_offsets[layout.root_slot_names[0]]
        out.append(f"    lea rsi, [rbp - {abs(first_root_offset)}]")
        out.append(f"    mov edx, {len(layout.root_slot_names)}")
        out.append("    call rt_root_frame_init")
        out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
        out.append(f"    lea rsi, [rbp - {abs(layout.root_frame_offset)}]")
        out.append("    call rt_push_roots")

    _emit_runtime_call_hook(
        fn_name=target_label,
        phase="before",
        out=out,
        label_counter=label_counter,
    )
    _emit_root_slot_updates(layout, out)
    out.append("    call rt_thread_state")
    out.append("    mov rdi, rax")
    out.append(f"    lea rsi, [rip + {ctor_layout.type_symbol}]")
    out.append(f"    mov rdx, {ctor_layout.payload_bytes}")
    out.append("    call rt_alloc_obj")
    _emit_runtime_call_hook(
        fn_name=target_label,
        phase="after",
        out=out,
        label_counter=label_counter,
    )

    for field_index, field_name in enumerate(ctor_layout.field_names):
        field_offset = 24 + (8 * field_index)
        value_offset = layout.slot_offsets[field_name]
        out.append(f"    mov rcx, {_offset_operand(value_offset)}")
        out.append(f"    mov qword ptr [rax + {field_offset}], rcx")

    out.append(f"    jmp {epilogue}")

    out.append(f"{epilogue}:")
    if layout.root_slot_names:
        out.append("    push rax")
        out.append(f"    mov rdi, {_offset_operand(layout.thread_state_offset)}")
        out.append("    call rt_pop_roots")
        out.append("    pop rax")
    out.append("    mov rsp, rbp")
    out.append("    pop rbp")
    out.append("    ret")


def emit_asm(module_ast: ModuleAst) -> str:
    lines: list[str] = [".intel_syntax noprefix"]

    _emit_type_metadata_section(module_ast, lines)
    string_literal_labels = _emit_string_literal_section(module_ast, lines)

    lines.append("")
    lines.append(".text")

    method_labels: dict[tuple[str, str], str] = {}
    for cls in module_ast.classes:
        for method in cls.methods:
            method_labels[(cls.name, method.name)] = _mangle_method_symbol(cls.name, method.name)

    constructor_layouts: dict[str, ConstructorLayout] = {}
    constructor_labels: dict[str, str] = {}
    for cls in module_ast.classes:
        ctor_label = _mangle_constructor_symbol(cls.name)
        ctor_layout = ConstructorLayout(
            class_name=cls.name,
            label=ctor_label,
            type_symbol=_mangle_type_symbol(cls.name),
            payload_bytes=len(cls.fields) * 8,
            field_names=[field.name for field in cls.fields],
        )
        constructor_layouts[cls.name] = ctor_layout
        constructor_labels[cls.name] = ctor_label

    for fn in module_ast.functions:
        if fn.is_extern:
            continue
        lines.append("")
        _emit_function(fn, lines, method_labels, constructor_labels, string_literal_labels)

    for cls in module_ast.classes:
        for method in cls.methods:
            lines.append("")
            method_label = method_labels[(cls.name, method.name)]
            method_fn = _method_function_decl(cls, method, method_label)
            _emit_function(
                method_fn,
                lines,
                method_labels,
                constructor_labels,
                string_literal_labels,
                label=method_label,
            )

    for cls in module_ast.classes:
        lines.append("")
        _emit_constructor_function(
            cls,
            constructor_layouts[cls.name],
            lines,
        )

    lines.append("")
    lines.append('.section .note.GNU-stack,"",@progbits')
    lines.append("")
    return "\n".join(lines)
