from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.emitter_fn import emit_constructor, emit_function, emit_method
from compiler.codegen.metadata import TypeMetadata
from compiler.codegen.strings import emit_string_literal_section, escape_c_string
from compiler.semantic.ir import *


def generate_module(codegen, program, declaration_tables, type_metadata: TypeMetadata) -> str:
    emit_type_metadata_section(codegen, type_metadata)
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
        for constructor in cls.constructors:
            codegen.asm.blank()
            emit_constructor(codegen, declaration_tables, cls, constructor)

    emit_runtime_panic_messages_section(codegen)
    codegen.asm.blank()
    codegen.asm.directive('.section .note.GNU-stack,"",@progbits')
    codegen.asm.blank()
    return codegen.asm.build()


def emit_type_metadata_section(codegen, type_metadata: TypeMetadata) -> None:
    if not type_metadata.classes and not type_metadata.extra_runtime_types and not type_metadata.interfaces:
        return

    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for cls in type_metadata.classes:
        for alias in cls.aliases:
            codegen.asm.label(codegen_symbols.mangle_type_name_symbol(alias))
        codegen.asm.asciz(cls.display_name)
    for runtime_type in type_metadata.extra_runtime_types:
        for alias in runtime_type.aliases:
            codegen.asm.label(codegen_symbols.mangle_type_name_symbol(alias))
        codegen.asm.asciz(runtime_type.display_name)
    for interface in type_metadata.interfaces:
        codegen.asm.label(codegen_symbols.mangle_interface_name_symbol(interface.display_name))
        codegen.asm.asciz(interface.display_name)
    for cls in type_metadata.classes:
        if cls.pointer_offsets_symbol is None:
            continue
        codegen.asm.label(cls.pointer_offsets_symbol)
        for offset in cls.pointer_offsets:
            codegen.asm.instr(f".long {offset}")

    codegen.asm.blank()
    codegen.asm.directive(".data")
    for interface in type_metadata.interfaces:
        codegen.asm.instr(".p2align 3")
        codegen.asm.label(interface.descriptor_symbol)
        _emit_rt_interface_record(
            codegen,
            name_sym=codegen_symbols.mangle_interface_name_symbol(interface.display_name),
            method_count=interface.method_count,
        )

    for cls in type_metadata.classes:
        if not cls.interface_impls:
            continue

        for interface_impl in cls.interface_impls:
            codegen.asm.instr(".p2align 3")
            codegen.asm.label(interface_impl.method_table_symbol)
            for method_label in interface_impl.method_labels:
                codegen.asm.instr(f".quad {method_label}")

        codegen.asm.instr(".p2align 3")
        codegen.asm.label(cls.interface_impls_symbol)
        for interface_impl in cls.interface_impls:
            codegen.asm.instr(f".quad {interface_impl.descriptor_symbol}")
            codegen.asm.instr(f".quad {interface_impl.method_table_symbol}")
            codegen.asm.instr(f".long {interface_impl.method_count}")
            codegen.asm.instr(".long 0")

    for cls in type_metadata.classes:
        if cls.class_vtable_symbol is None:
            continue

        codegen.asm.instr(".p2align 3")
        codegen.asm.label(cls.class_vtable_symbol)
        for method_label in cls.class_vtable_labels:
            codegen.asm.instr(f".quad {method_label}")

    for cls in type_metadata.classes:
        codegen.asm.instr(".p2align 3")
        for alias in cls.aliases:
            codegen.asm.label(codegen_symbols.mangle_type_symbol(alias))
        name_sym = codegen_symbols.mangle_type_name_symbol(cls.display_name)
        if cls.pointer_offsets_symbol is None:
            type_flags = 0
            pointer_offsets_sym = "0"
            pointer_offsets_count = 0
        else:
            pointer_offsets_sym = cls.pointer_offsets_symbol
            pointer_offsets_count = len(cls.pointer_offsets)
            type_flags = 1
        super_type_sym = cls.superclass_symbol or "0"
        interfaces_sym = cls.interface_impls_symbol or "0"
        interface_count = len(cls.interface_impls)
        class_vtable_sym = cls.class_vtable_symbol or "0"
        class_vtable_count = len(cls.class_vtable_labels)
        _emit_rt_type_record(
            codegen,
            flags=type_flags,
            name_sym=name_sym,
            pointer_offsets_sym=pointer_offsets_sym,
            pointer_offsets_count=pointer_offsets_count,
            super_type_sym=super_type_sym,
            interfaces_sym=interfaces_sym,
            interface_count=interface_count,
            class_vtable_sym=class_vtable_sym,
            class_vtable_count=class_vtable_count,
        )

    for runtime_type in type_metadata.extra_runtime_types:
        type_sym = codegen_symbols.mangle_type_symbol(runtime_type.canonical_type_name)
        name_sym = codegen_symbols.mangle_type_name_symbol(runtime_type.display_name)
        codegen.asm.instr(".p2align 3")
        for alias in runtime_type.aliases:
            codegen.asm.label(codegen_symbols.mangle_type_symbol(alias))
        _emit_rt_type_record(
            codegen,
            flags=0,
            name_sym=name_sym,
            pointer_offsets_sym="0",
            pointer_offsets_count=0,
            super_type_sym="0",
            interfaces_sym="0",
            interface_count=0,
            class_vtable_sym="0",
            class_vtable_count=0,
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
    super_type_sym: str,
    interfaces_sym: str,
    interface_count: int,
    class_vtable_sym: str,
    class_vtable_count: int,
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
    codegen.asm.instr(f".quad {super_type_sym}")
    codegen.asm.instr(f".quad {interfaces_sym}")
    codegen.asm.instr(f".long {interface_count}")
    codegen.asm.instr(".long 0")
    codegen.asm.instr(f".quad {class_vtable_sym}")
    codegen.asm.instr(f".long {class_vtable_count}")
    codegen.asm.instr(".long 0")


def emit_runtime_panic_messages_section(codegen) -> None:
    if not codegen.runtime_panic_message_labels:
        return
    codegen.asm.blank()
    codegen.asm.directive(".section .rodata")
    for message, label in codegen.runtime_panic_message_labels.items():
        codegen.asm.label(label)
        codegen.asm.asciz(escape_c_string(message))
