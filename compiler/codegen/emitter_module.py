from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.emitter_fn import emit_constructor, emit_function, emit_method
from compiler.codegen.strings import emit_string_literal_section, escape_c_string
from compiler.codegen.walk import walk_codegen_program_expressions
from compiler.semantic.ir import *


def generate_module(codegen, program) -> str:
    emit_type_metadata_section(codegen, program)
    codegen.string_literal_labels = emit_string_literal_section(codegen, program)

    codegen.asm.blank()
    codegen.asm.directive(".text")

    declaration_tables = codegen.build_declaration_tables()

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


def emit_type_metadata_section(codegen, program) -> None:
    class_aliases_by_name: dict[str, tuple[object, list[str], str]] = {}
    for cls in program.classes:
        qualified_name = _qualified_class_type_name(cls)
        aliases = [cls.class_id.name]
        if qualified_name != cls.class_id.name:
            aliases.append(qualified_name)
        display_name = qualified_name if qualified_name != cls.class_id.name else cls.class_id.name
        for alias in aliases:
            class_aliases_by_name[alias] = (cls, aliases, display_name)

    cast_type_names = collect_reference_cast_types(program)
    extra_type_names = sorted(name for name in cast_type_names if name not in class_aliases_by_name)
    if not class_aliases_by_name and not extra_type_names:
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
    for symbol, pointer_offsets in pointer_offset_symbols.values():
        codegen.asm.label(symbol)
        for offset in pointer_offsets:
            codegen.asm.instr(f".long {offset}")

    codegen.asm.blank()
    codegen.asm.directive(".data")
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
        _emit_rt_type_record(
            codegen,
            flags=type_flags,
            name_sym=name_sym,
            pointer_offsets_sym=pointer_offsets_sym,
            pointer_offsets_count=pointer_offsets_count,
        )

    for type_name in extra_type_names:
        type_sym = codegen_symbols.mangle_type_symbol(type_name)
        name_sym = codegen_symbols.mangle_type_name_symbol(type_name)
        codegen.asm.instr(".p2align 3")
        codegen.asm.label(type_sym)
        _emit_rt_type_record(codegen, flags=0, name_sym=name_sym, pointer_offsets_sym="0", pointer_offsets_count=0)


def _emit_rt_type_record(codegen, *, flags: int, name_sym: str, pointer_offsets_sym: str, pointer_offsets_count: int) -> None:
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
    codegen.asm.instr(".quad 0")
    codegen.asm.instr(".long 0")
    codegen.asm.instr(".long 0")


def emit_runtime_panic_messages_section(codegen) -> None:
    if not codegen.runtime_panic_message_labels:
        return
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for message, label in codegen.runtime_panic_message_labels.items():
        codegen.asm.label(label)
        codegen.asm.asciz(escape_c_string(message))


def collect_reference_cast_types(program) -> list[str]:
    names: set[str] = {cls.class_id.name for cls in program.classes}
    walk_codegen_program_expressions(program, lambda expr: _collect_reference_cast_type(expr, names))
    return sorted(names)


def _qualified_class_type_name(cls) -> str:
    owner_dotted = ".".join(cls.class_id.module_path)
    return f"{owner_dotted}::{cls.class_id.name}"


def _collect_reference_cast_type(expr: SemanticExpr, out: set[str]) -> None:
    if isinstance(expr, CastExprS):
        if codegen_types.is_reference_type_name(expr.target_type_name):
            out.add(expr.target_type_name)
