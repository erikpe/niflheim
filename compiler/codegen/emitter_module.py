from __future__ import annotations

from typing import TYPE_CHECKING

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.ast_nodes import BinaryExpr, BlockStmt, CallExpr, CastExpr, ExprStmt, IfStmt, ReturnStmt, Statement, UnaryExpr, VarDeclStmt, WhileStmt
from compiler.codegen.emitter_fn import emit_constructor_function, emit_function, method_function_decl
from compiler.codegen.strings import collect_string_literals, decode_string_literal, escape_asm_string_bytes, escape_c_string

if TYPE_CHECKING:
    from compiler.codegen.generator import CodeGenerator


def collect_reference_cast_types_from_expr(expr, out: set[str]) -> None:
    if isinstance(expr, CastExpr):
        target_type_name = codegen_types.type_ref_name(expr.type_ref)
        if codegen_types.is_reference_type_name(target_type_name):
            out.add(target_type_name)
        collect_reference_cast_types_from_expr(expr.operand, out)
        return
    if isinstance(expr, BinaryExpr):
        collect_reference_cast_types_from_expr(expr.left, out)
        collect_reference_cast_types_from_expr(expr.right, out)
        return
    if isinstance(expr, UnaryExpr):
        collect_reference_cast_types_from_expr(expr.operand, out)
        return
    if isinstance(expr, CallExpr):
        collect_reference_cast_types_from_expr(expr.callee, out)
        for arg in expr.arguments:
            collect_reference_cast_types_from_expr(arg, out)


def collect_reference_cast_types_from_stmt(stmt: Statement, out: set[str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        if stmt.initializer is not None:
            collect_reference_cast_types_from_expr(stmt.initializer, out)
        return
    if isinstance(stmt, ExprStmt):
        collect_reference_cast_types_from_expr(stmt.expression, out)
        return
    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            collect_reference_cast_types_from_expr(stmt.value, out)
        return
    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            collect_reference_cast_types_from_stmt(nested, out)
        return
    if isinstance(stmt, IfStmt):
        collect_reference_cast_types_from_expr(stmt.condition, out)
        collect_reference_cast_types_from_stmt(stmt.then_branch, out)
        if stmt.else_branch is not None:
            collect_reference_cast_types_from_stmt(stmt.else_branch, out)
        return
    if isinstance(stmt, WhileStmt):
        collect_reference_cast_types_from_expr(stmt.condition, out)
        collect_reference_cast_types_from_stmt(stmt.body, out)


def collect_reference_cast_types(module_ast) -> list[str]:
    names: set[str] = set()
    for cls in module_ast.classes:
        names.add(cls.name)
    for fn in module_ast.functions:
        if fn.body is None:
            continue
        for stmt in fn.body.statements:
            collect_reference_cast_types_from_stmt(stmt, names)
    for cls in module_ast.classes:
        for method in cls.methods:
            for stmt in method.body.statements:
                collect_reference_cast_types_from_stmt(stmt, names)
    return sorted(names)


def emit_string_literal_section(codegen: CodeGenerator) -> dict[str, tuple[str, int]]:
    string_literals = collect_string_literals(codegen.module_ast)
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


def emit_type_metadata_section(codegen: CodeGenerator) -> None:
    class_type_names = [cls.name for cls in codegen.module_ast.classes]
    cast_type_names = collect_reference_cast_types(codegen.module_ast)
    type_names = sorted(set(class_type_names) | set(cast_type_names))
    if not type_names:
        return

    class_decls_by_name = {cls.name: cls for cls in codegen.module_ast.classes}
    pointer_offset_symbols: dict[str, tuple[str, list[int]]] = {}
    for type_name in type_names:
        class_decl = class_decls_by_name.get(type_name)
        if class_decl is None:
            continue
        pointer_offsets = [
            24 + (8 * field_index)
            for field_index, field in enumerate(class_decl.fields)
            if codegen_types.is_reference_type_name(codegen_types.type_ref_name(field.type_ref))
        ]
        if pointer_offsets:
            pointer_offset_symbols[type_name] = (
                f"{codegen_symbols.mangle_type_name_symbol(type_name)}__ptr_offsets",
                pointer_offsets,
            )

    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for type_name in type_names:
        codegen.asm.label(codegen_symbols.mangle_type_name_symbol(type_name))
        codegen.asm.asciz(type_name)
    for symbol, pointer_offsets in pointer_offset_symbols.values():
        codegen.asm.label(symbol)
        for offset in pointer_offsets:
            codegen.asm.instr(f".long {offset}")

    codegen.asm.blank()
    codegen.asm.directive(".data")
    for type_name in type_names:
        type_sym = codegen_symbols.mangle_type_symbol(type_name)
        name_sym = codegen_symbols.mangle_type_name_symbol(type_name)
        pointer_offsets_meta = pointer_offset_symbols.get(type_name)
        if pointer_offsets_meta is None:
            type_flags = 0
            pointer_offsets_sym = "0"
            pointer_offsets_count = 0
        else:
            pointer_offsets_sym = pointer_offsets_meta[0]
            pointer_offsets_count = len(pointer_offsets_meta[1])
            type_flags = 1
        codegen.asm.instr(".p2align 3")
        codegen.asm.label(type_sym)
        codegen.asm.instr(".long 0")
        codegen.asm.instr(f".long {type_flags}")
        codegen.asm.instr(".long 1")
        codegen.asm.instr(".long 8")
        codegen.asm.instr(".quad 0")
        codegen.asm.instr(f".quad {name_sym}")
        codegen.asm.instr(".quad 0")
        codegen.asm.instr(f".quad {pointer_offsets_sym}")
        codegen.asm.instr(f".long {pointer_offsets_count}")
        codegen.asm.instr(".long 0")


def emit_runtime_panic_messages_section(codegen: CodeGenerator) -> None:
    if not codegen.runtime_panic_message_labels:
        return

    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for message, label in codegen.runtime_panic_message_labels.items():
        codegen.asm.label(label)
        codegen.asm.asciz(escape_c_string(message))


def generate_module(codegen: CodeGenerator) -> str:
    emit_type_metadata_section(codegen)
    codegen.string_literal_labels = emit_string_literal_section(codegen)

    codegen.asm.blank()
    codegen.asm.directive(".text")

    codegen.build_symbol_tables()

    for fn in codegen.module_ast.functions:
        if fn.is_extern:
            continue
        codegen.asm.blank()
        emit_function(codegen, fn)

    for cls in codegen.module_ast.classes:
        for method in cls.methods:
            codegen.asm.blank()
            method_label = codegen.method_labels[(cls.name, method.name)]
            method_fn = method_function_decl(cls, method, method_label)
            emit_function(codegen, method_fn, label=method_label)

    for cls in codegen.module_ast.classes:
        codegen.asm.blank()
        emit_constructor_function(codegen, cls)

    emit_runtime_panic_messages_section(codegen)

    codegen.asm.blank()
    codegen.asm.directive('.section .note.GNU-stack,"",@progbits')
    codegen.asm.blank()
    return codegen.asm.build()
