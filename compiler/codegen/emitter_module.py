from __future__ import annotations

from typing import TYPE_CHECKING

from compiler.codegen.strings import collect_string_literals, decode_string_literal, escape_asm_string_bytes
from compiler.codegen.types import _is_reference_type_name, _type_ref_name

if TYPE_CHECKING:
    from compiler.codegen.legacy import CodeGenerator


def emit_string_literal_section(codegen: CodeGenerator) -> dict[str, tuple[str, int]]:
    string_literals = collect_string_literals(codegen.module_ast)
    labels: dict[str, tuple[str, int]] = {}
    if not string_literals:
        return labels

    codegen.out.append("")
    codegen.out.append(".section .rodata")
    for index, literal in enumerate(string_literals):
        label = f"__nif_str_lit_{index}"
        data = decode_string_literal(literal)
        labels[literal] = (label, len(data))
        codegen.out.append(f"{label}:")
        codegen.out.append(f'    .asciz "{escape_asm_string_bytes(data)}"')

    return labels


def emit_type_metadata_section(codegen: CodeGenerator) -> None:
    class_type_names = [cls.name for cls in codegen.module_ast.classes]
    cast_type_names = codegen._collect_reference_cast_types_proxy(codegen.module_ast)
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
            if _is_reference_type_name(_type_ref_name(field.type_ref))
        ]
        if pointer_offsets:
            pointer_offset_symbols[type_name] = (
                f"{codegen._mangle_type_name_symbol_proxy(type_name)}__ptr_offsets",
                pointer_offsets,
            )

    codegen.out.append("")
    codegen.out.append(".section .rodata")
    for type_name in type_names:
        codegen.out.append(f"{codegen._mangle_type_name_symbol_proxy(type_name)}:")
        codegen.out.append(f'    .asciz "{type_name}"')
    for symbol, pointer_offsets in pointer_offset_symbols.values():
        codegen.out.append(f"{symbol}:")
        for offset in pointer_offsets:
            codegen.out.append(f"    .long {offset}")

    codegen.out.append("")
    codegen.out.append(".data")
    for type_name in type_names:
        type_sym = codegen._mangle_type_symbol_proxy(type_name)
        name_sym = codegen._mangle_type_name_symbol_proxy(type_name)
        pointer_offsets_meta = pointer_offset_symbols.get(type_name)
        if pointer_offsets_meta is None:
            type_flags = 0
            pointer_offsets_sym = "0"
            pointer_offsets_count = 0
        else:
            pointer_offsets_sym = pointer_offsets_meta[0]
            pointer_offsets_count = len(pointer_offsets_meta[1])
            type_flags = 1
        codegen.out.append("    .p2align 3")
        codegen.out.append(f"{type_sym}:")
        codegen.out.append("    .long 0")
        codegen.out.append(f"    .long {type_flags}")
        codegen.out.append("    .long 1")
        codegen.out.append("    .long 8")
        codegen.out.append("    .quad 0")
        codegen.out.append(f"    .quad {name_sym}")
        codegen.out.append("    .quad 0")
        codegen.out.append(f"    .quad {pointer_offsets_sym}")
        codegen.out.append(f"    .long {pointer_offsets_count}")
        codegen.out.append("    .long 0")


def emit_runtime_panic_messages_section(codegen: CodeGenerator) -> None:
    if not codegen.runtime_panic_message_labels:
        return

    codegen.out.append("")
    codegen.out.append(".section .rodata")
    for message, label in codegen.runtime_panic_message_labels.items():
        codegen.out.append(f"{label}:")
        codegen.out.append(f'    .asciz "{codegen._escape_c_string_proxy(message)}"')


def generate_module(codegen: CodeGenerator) -> str:
    from compiler.codegen.legacy import _method_function_decl

    emit_type_metadata_section(codegen)
    codegen.string_literal_labels = emit_string_literal_section(codegen)

    codegen.asm.blank()
    codegen.asm.directive(".text")

    codegen._build_symbol_tables()

    for fn in codegen.module_ast.functions:
        if fn.is_extern:
            continue
        codegen.asm.blank()
        codegen._emit_function(fn)

    for cls in codegen.module_ast.classes:
        for method in cls.methods:
            codegen.asm.blank()
            method_label = codegen.method_labels[(cls.name, method.name)]
            method_fn = _method_function_decl(cls, method, method_label)
            codegen._emit_function(method_fn, label=method_label)

    for cls in codegen.module_ast.classes:
        codegen.asm.blank()
        codegen._emit_constructor_function(cls)

    emit_runtime_panic_messages_section(codegen)

    codegen.asm.blank()
    codegen.asm.directive('.section .note.GNU-stack,"",@progbits')
    codegen.asm.blank()
    return codegen.asm.build()