from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.emitter_fn import emit_constructor, emit_function, emit_method
from compiler.codegen.strings import emit_string_literal_section, escape_c_string
from compiler.semantic.ir import *


def generate_module(codegen, program) -> str:
    declaration_tables = codegen.build_declaration_tables()
    emit_type_metadata_section(codegen, program, declaration_tables)
    codegen.string_literal_labels = emit_string_literal_section(codegen, program)

    codegen.asm.blank()
    codegen.asm.directive(".text")

    for fn in program.functions:
        if fn.is_extern:
            continue
        codegen.asm.blank()
        emit_function(codegen, declaration_tables, fn)

    for cls in program.classes:
        for method in cls.methods:
            codegen.asm.blank()
            emit_method(codegen, declaration_tables, cls, method)

    for cls in program.classes:
        codegen.asm.blank()
        emit_constructor(codegen, declaration_tables, cls)

    emit_runtime_panic_messages_section(codegen)
    codegen.asm.blank()
    codegen.asm.directive('.section .note.GNU-stack,"",@progbits')
    codegen.asm.blank()
    return codegen.asm.build()


def emit_type_metadata_section(codegen, program, declaration_tables) -> None:
    class_aliases_by_name: dict[str, tuple[object, list[str], str]] = {}
    for cls in program.classes:
        qualified_name = _qualified_class_type_name(cls)
        aliases = [cls.class_id.name]
        if qualified_name != cls.class_id.name:
            aliases.append(qualified_name)
        display_name = qualified_name if qualified_name != cls.class_id.name else cls.class_id.name
        for alias in aliases:
            class_aliases_by_name[alias] = (cls, aliases, display_name)

    interface_decls = [interface for module in program.ordered_modules for interface in module.interfaces]
    interface_methods_by_id = {
        method.method_id: method for interface in interface_decls for method in interface.methods
    }

    cast_type_names = collect_reference_cast_types(program, interface_decls)
    extra_type_names = sorted(name for name in cast_type_names if name not in class_aliases_by_name)
    if not class_aliases_by_name and not extra_type_names and not interface_decls:
        return

    pointer_offset_symbols: dict[str, tuple[str, list[int]]] = {}
    emitted_classes: set[tuple[tuple[str, ...], str]] = set()
    for cls, aliases, _display_name in class_aliases_by_name.values():
        class_key = (cls.class_id.module_path, cls.class_id.name)
        if class_key in emitted_classes:
            continue
        emitted_classes.add(class_key)
        pointer_offsets = [
            24 + (8 * field_index)
            for field_index, field in enumerate(cls.fields)
            if codegen_types.is_reference_type_name(field.type_name)
        ]
        if pointer_offsets:
            pointer_offset_symbols[_qualified_class_type_name(cls)] = (
                f"{codegen_symbols.mangle_type_name_symbol(_qualified_class_type_name(cls))}__ptr_offsets",
                pointer_offsets,
            )

    interface_display_names_by_id = {
        interface.interface_id: _qualified_interface_type_name(interface.interface_id) for interface in interface_decls
    }

    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    emitted_name_records: set[tuple[tuple[str, ...], str]] = set()
    for cls, aliases, display_name in class_aliases_by_name.values():
        class_key = (cls.class_id.module_path, cls.class_id.name)
        if class_key in emitted_name_records:
            continue
        emitted_name_records.add(class_key)
        for alias in aliases:
            codegen.asm.label(codegen_symbols.mangle_type_name_symbol(alias))
        codegen.asm.asciz(display_name)
    for type_name in extra_type_names:
        codegen.asm.label(codegen_symbols.mangle_type_name_symbol(type_name))
        codegen.asm.asciz(type_name)
    for interface in interface_decls:
        codegen.asm.label(codegen_symbols.mangle_interface_name_symbol(interface_display_names_by_id[interface.interface_id]))
        codegen.asm.asciz(interface_display_names_by_id[interface.interface_id])
    for symbol, pointer_offsets in pointer_offset_symbols.values():
        codegen.asm.label(symbol)
        for offset in pointer_offsets:
            codegen.asm.instr(f".long {offset}")

    codegen.asm.blank()
    codegen.asm.directive(".data")
    for interface in interface_decls:
        codegen.asm.instr(".p2align 3")
        codegen.asm.label(declaration_tables.interface_descriptor_symbols_by_id[interface.interface_id])
        _emit_rt_interface_record(
            codegen,
            name_sym=codegen_symbols.mangle_interface_name_symbol(interface_display_names_by_id[interface.interface_id]),
            method_count=len(interface.methods),
        )

    class_interface_method_table_symbols: dict[tuple[tuple[str, ...], str, tuple[str, ...], str], str] = {}
    class_interface_impls_symbols: dict[tuple[tuple[str, ...], str], tuple[str, int]] = {}
    interface_decls_by_id = {interface.interface_id: interface for interface in interface_decls}
    for cls in program.classes:
        class_key = (cls.class_id.module_path, cls.class_id.name)
        if not cls.implemented_interfaces:
            continue

        class_type_name = _qualified_class_type_name(cls)
        impl_table_symbol = codegen_symbols.mangle_class_interface_impls_symbol(class_type_name)
        class_interface_impls_symbols[class_key] = (impl_table_symbol, len(cls.implemented_interfaces))

        for interface_id in cls.implemented_interfaces:
            interface = interface_decls_by_id[interface_id]
            table_key = (cls.class_id.module_path, cls.class_id.name, interface_id.module_path, interface_id.name)
            class_interface_method_table_symbols[table_key] = codegen_symbols.mangle_interface_method_table_symbol(
                class_type_name, interface_display_names_by_id[interface_id]
            )

            codegen.asm.instr(".p2align 3")
            codegen.asm.label(class_interface_method_table_symbols[table_key])
            for interface_method in interface.methods:
                method_id = MethodId(
                    module_path=cls.class_id.module_path,
                    class_name=cls.class_id.name,
                    name=interface_methods_by_id[interface_method.method_id].method_id.name,
                )
                codegen.asm.instr(f".quad {declaration_tables.method_labels_by_id[method_id]}")

        codegen.asm.instr(".p2align 3")
        codegen.asm.label(impl_table_symbol)
        for interface_id in cls.implemented_interfaces:
            table_key = (cls.class_id.module_path, cls.class_id.name, interface_id.module_path, interface_id.name)
            interface = interface_decls_by_id[interface_id]
            codegen.asm.instr(
                f".quad {declaration_tables.interface_descriptor_symbols_by_id[interface_id]}"
            )
            codegen.asm.instr(f".quad {class_interface_method_table_symbols[table_key]}")
            codegen.asm.instr(f".long {len(interface.methods)}")
            codegen.asm.instr(".long 0")

    emitted_type_records: set[tuple[tuple[str, ...], str]] = set()
    for cls, aliases, display_name in class_aliases_by_name.values():
        class_key = (cls.class_id.module_path, cls.class_id.name)
        if class_key in emitted_type_records:
            continue
        emitted_type_records.add(class_key)
        codegen.asm.instr(".p2align 3")
        for alias in aliases:
            codegen.asm.label(codegen_symbols.mangle_type_symbol(alias))
        name_sym = codegen_symbols.mangle_type_name_symbol(display_name)
        pointer_offsets_meta = pointer_offset_symbols.get(_qualified_class_type_name(cls))
        if pointer_offsets_meta is None:
            type_flags = 0
            pointer_offsets_sym = "0"
            pointer_offsets_count = 0
        else:
            pointer_offsets_sym = pointer_offsets_meta[0]
            pointer_offsets_count = len(pointer_offsets_meta[1])
            type_flags = 1
        interfaces_sym, interface_count = class_interface_impls_symbols.get(class_key, ("0", 0))
        _emit_rt_type_record(
            codegen,
            flags=type_flags,
            name_sym=name_sym,
            pointer_offsets_sym=pointer_offsets_sym,
            pointer_offsets_count=pointer_offsets_count,
            interfaces_sym=interfaces_sym,
            interface_count=interface_count,
        )

    for type_name in extra_type_names:
        type_sym = codegen_symbols.mangle_type_symbol(type_name)
        name_sym = codegen_symbols.mangle_type_name_symbol(type_name)
        codegen.asm.instr(".p2align 3")
        codegen.asm.label(type_sym)
        _emit_rt_type_record(
            codegen,
            flags=0,
            name_sym=name_sym,
            pointer_offsets_sym="0",
            pointer_offsets_count=0,
            interfaces_sym="0",
            interface_count=0,
        )


def _emit_rt_interface_record(codegen, *, name_sym: str, method_count: int) -> None:
    codegen.asm.instr(f".quad {name_sym}")
    codegen.asm.instr(f".long {method_count}")
    codegen.asm.instr(".long 0")


def _emit_rt_type_record(
    codegen,
    *,
    flags: int,
    name_sym: str,
    pointer_offsets_sym: str,
    pointer_offsets_count: int,
    interfaces_sym: str,
    interface_count: int,
) -> None:
    codegen.asm.instr(".long 0")
    codegen.asm.instr(f".long {flags}")
    codegen.asm.instr(".long 1")
    codegen.asm.instr(".long 8")
    codegen.asm.instr(".quad 0")
    codegen.asm.instr(f".quad {name_sym}")
    codegen.asm.instr(".quad 0")
    codegen.asm.instr(f".quad {pointer_offsets_sym}")
    codegen.asm.instr(f".long {pointer_offsets_count}")
    codegen.asm.instr(".long 0")
    codegen.asm.instr(f".quad {interfaces_sym}")
    codegen.asm.instr(f".long {interface_count}")
    codegen.asm.instr(".long 0")


def emit_runtime_panic_messages_section(codegen) -> None:
    if not codegen.runtime_panic_message_labels:
        return
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for message, label in codegen.runtime_panic_message_labels.items():
        codegen.asm.label(label)
        codegen.asm.asciz(escape_c_string(message))


def collect_reference_cast_types(program, interfaces: list[SemanticInterface]) -> list[str]:
    names: set[str] = {cls.class_id.name for cls in program.classes}
    local_interface_names_by_module = {
        module.module_path: {interface.interface_id.name for interface in module.interfaces}
        for module in program.ordered_modules
    }
    for fn in program.functions:
        if fn.body is not None:
            _collect_reference_cast_types_from_block(fn.body, fn.function_id.module_path, local_interface_names_by_module, names)
    for cls in program.classes:
        for field in cls.fields:
            if field.initializer is not None:
                _collect_reference_cast_types_from_expr(
                    field.initializer,
                    cls.class_id.module_path,
                    local_interface_names_by_module,
                    names,
                )
        for method in cls.methods:
            _collect_reference_cast_types_from_block(
                method.body,
                method.method_id.module_path,
                local_interface_names_by_module,
                names,
            )
    return sorted(names)


def _qualified_class_type_name(cls) -> str:
    owner_dotted = ".".join(cls.class_id.module_path)
    return f"{owner_dotted}::{cls.class_id.name}"


def _qualified_interface_type_name(interface_id: InterfaceId) -> str:
    owner_dotted = ".".join(interface_id.module_path)
    return f"{owner_dotted}::{interface_id.name}"


def _collect_reference_cast_types_from_block(
    block: SemanticBlock,
    module_path: tuple[str, ...],
    local_interface_names_by_module: dict[tuple[str, ...], set[str]],
    out: set[str],
) -> None:
    for stmt in block.statements:
        _collect_reference_cast_types_from_stmt(stmt, module_path, local_interface_names_by_module, out)


def _collect_reference_cast_types_from_stmt(
    stmt: SemanticStmt,
    module_path: tuple[str, ...],
    local_interface_names_by_module: dict[tuple[str, ...], set[str]],
    out: set[str],
) -> None:
    if isinstance(stmt, SemanticBlock):
        _collect_reference_cast_types_from_block(stmt, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticVarDecl):
        if stmt.initializer is not None:
            _collect_reference_cast_types_from_expr(stmt.initializer, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticAssign):
        _collect_reference_cast_types_from_expr(stmt.value, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticExprStmt):
        _collect_reference_cast_types_from_expr(stmt.expr, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticReturn):
        if stmt.value is not None:
            _collect_reference_cast_types_from_expr(stmt.value, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticIf):
        _collect_reference_cast_types_from_expr(stmt.condition, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_block(stmt.then_block, module_path, local_interface_names_by_module, out)
        if stmt.else_block is not None:
            _collect_reference_cast_types_from_block(stmt.else_block, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticWhile):
        _collect_reference_cast_types_from_expr(stmt.condition, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_block(stmt.body, module_path, local_interface_names_by_module, out)
        return
    if isinstance(stmt, SemanticForIn):
        _collect_reference_cast_types_from_expr(stmt.collection, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_block(stmt.body, module_path, local_interface_names_by_module, out)


def _collect_reference_cast_types_from_expr(
    expr: SemanticExpr,
    module_path: tuple[str, ...],
    local_interface_names_by_module: dict[tuple[str, ...], set[str]],
    out: set[str],
) -> None:
    if isinstance(expr, CastExprS):
        if codegen_types.is_reference_type_name(expr.target_type_name) and not _is_interface_type_name(
            module_path, expr.target_type_name, local_interface_names_by_module
        ):
            out.add(expr.target_type_name)
        _collect_reference_cast_types_from_expr(expr.operand, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, TypeTestExprS):
        if codegen_types.is_reference_type_name(expr.target_type_name) and not _is_interface_type_name(
            module_path, expr.target_type_name, local_interface_names_by_module
        ):
            out.add(expr.target_type_name)
        _collect_reference_cast_types_from_expr(expr.operand, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, UnaryExprS):
        _collect_reference_cast_types_from_expr(expr.operand, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, BinaryExprS):
        _collect_reference_cast_types_from_expr(expr.left, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_expr(expr.right, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, FieldReadExpr):
        _collect_reference_cast_types_from_expr(expr.receiver, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, FunctionCallExpr | StaticMethodCallExpr | ConstructorCallExpr):
        for arg in expr.args:
            _collect_reference_cast_types_from_expr(arg, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, CallableValueCallExpr):
        for arg in expr.args:
            _collect_reference_cast_types_from_expr(arg, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_expr(expr.callee, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, InstanceMethodCallExpr | InterfaceMethodCallExpr):
        _collect_reference_cast_types_from_expr(expr.receiver, module_path, local_interface_names_by_module, out)
        for arg in expr.args:
            _collect_reference_cast_types_from_expr(arg, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, ArrayLenExpr):
        _collect_reference_cast_types_from_expr(expr.target, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, IndexReadExpr):
        _collect_reference_cast_types_from_expr(expr.target, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_expr(expr.index, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, SliceReadExpr):
        _collect_reference_cast_types_from_expr(expr.target, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_expr(expr.begin, module_path, local_interface_names_by_module, out)
        _collect_reference_cast_types_from_expr(expr.end, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, ArrayCtorExprS):
        _collect_reference_cast_types_from_expr(expr.length_expr, module_path, local_interface_names_by_module, out)
        return
    if isinstance(expr, SyntheticExpr):
        for arg in expr.args:
            _collect_reference_cast_types_from_expr(arg, module_path, local_interface_names_by_module, out)


def _is_interface_type_name(
    module_path: tuple[str, ...],
    type_name: str,
    local_interface_names_by_module: dict[tuple[str, ...], set[str]],
) -> bool:
    if "::" in type_name:
        owner_dotted, interface_name = type_name.split("::", 1)
        return interface_name in local_interface_names_by_module.get(tuple(owner_dotted.split(".")), set())
    return type_name in local_interface_names_by_module.get(module_path, set())
