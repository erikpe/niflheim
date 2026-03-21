from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import compiler.codegen.symbols as codegen_symbols

from compiler.common.type_shapes import is_reference_type_name
from compiler.codegen.walk import walk_block_expressions, walk_expression
from compiler.semantic.ir import *
from compiler.semantic.linker import LinkedSemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceId, MethodId

if TYPE_CHECKING:
    from compiler.codegen.program_generator import DeclarationTables


@dataclass(frozen=True)
class InterfaceMetadataRecord:
    interface_id: InterfaceId
    display_name: str
    descriptor_symbol: str
    method_count: int


@dataclass(frozen=True)
class InterfaceImplMetadataRecord:
    interface_id: InterfaceId
    descriptor_symbol: str
    display_name: str
    method_count: int
    method_table_symbol: str
    method_labels: tuple[str, ...]


@dataclass(frozen=True)
class ClassMetadataRecord:
    class_id: ClassId
    qualified_type_name: str
    display_name: str
    aliases: tuple[str, ...]
    pointer_offsets_symbol: str | None
    pointer_offsets: tuple[int, ...]
    interface_impls_symbol: str | None
    interface_impls: tuple[InterfaceImplMetadataRecord, ...]


@dataclass(frozen=True)
class TypeMetadata:
    classes: tuple[ClassMetadataRecord, ...]
    interfaces: tuple[InterfaceMetadataRecord, ...]
    extra_runtime_type_names: tuple[str, ...]


def build_type_metadata(program: LinkedSemanticProgram, declaration_tables: DeclarationTables) -> TypeMetadata:
    interface_decls = [interface for module in program.ordered_modules for interface in module.interfaces]
    interfaces_by_id = {interface.interface_id: interface for interface in interface_decls}

    interface_records = tuple(
        InterfaceMetadataRecord(
            interface_id=interface.interface_id,
            display_name=_qualified_interface_type_name(interface.interface_id),
            descriptor_symbol=declaration_tables.interface_descriptor_symbols_by_id[interface.interface_id],
            method_count=len(interface.methods),
        )
        for interface in interface_decls
    )

    class_records: list[ClassMetadataRecord] = []
    class_alias_names: set[str] = set()
    for cls in program.classes:
        qualified_type_name = _qualified_class_type_name(cls.class_id)
        aliases = [cls.class_id.name]
        if qualified_type_name != cls.class_id.name:
            aliases.append(qualified_type_name)
        class_alias_names.update(aliases)

        display_name = qualified_type_name if qualified_type_name != cls.class_id.name else cls.class_id.name
        pointer_offsets = tuple(
            24 + (8 * field_index)
            for field_index, field in enumerate(cls.fields)
            if is_reference_type_name(field.type_name)
        )
        pointer_offsets_symbol = None
        if pointer_offsets:
            pointer_offsets_symbol = f"{codegen_symbols.mangle_type_name_symbol(qualified_type_name)}__ptr_offsets"

        interface_impls: list[InterfaceImplMetadataRecord] = []
        interface_impls_symbol: str | None = None
        if cls.implemented_interfaces:
            interface_impls_symbol = codegen_symbols.mangle_class_interface_impls_symbol(qualified_type_name)
            for interface_id in cls.implemented_interfaces:
                interface = interfaces_by_id[interface_id]
                interface_display_name = _qualified_interface_type_name(interface_id)
                method_labels = tuple(
                    declaration_tables.method_labels_by_id[
                        MethodId(
                            module_path=cls.class_id.module_path,
                            class_name=cls.class_id.name,
                            name=interface_method.method_id.name,
                        )
                    ]
                    for interface_method in interface.methods
                )
                interface_impls.append(
                    InterfaceImplMetadataRecord(
                        interface_id=interface_id,
                        descriptor_symbol=declaration_tables.interface_descriptor_symbols_by_id[interface_id],
                        display_name=interface_display_name,
                        method_count=len(interface.methods),
                        method_table_symbol=codegen_symbols.mangle_interface_method_table_symbol(
                            qualified_type_name, interface_display_name
                        ),
                        method_labels=method_labels,
                    )
                )

        class_records.append(
            ClassMetadataRecord(
                class_id=cls.class_id,
                qualified_type_name=qualified_type_name,
                display_name=display_name,
                aliases=tuple(aliases),
                pointer_offsets_symbol=pointer_offsets_symbol,
                pointer_offsets=pointer_offsets,
                interface_impls_symbol=interface_impls_symbol,
                interface_impls=tuple(interface_impls),
            )
        )

    extra_runtime_type_names = tuple(
        sorted(
            type_name
            for type_name in _collect_reference_cast_type_names(program, declaration_tables)
            if type_name not in class_alias_names
        )
    )

    return TypeMetadata(
        classes=tuple(class_records),
        interfaces=interface_records,
        extra_runtime_type_names=extra_runtime_type_names,
    )


def _collect_reference_cast_type_names(
    program: LinkedSemanticProgram, declaration_tables: DeclarationTables
) -> set[str]:
    names: set[str] = set()

    def _collect_expr(expr: SemanticExpr, module_path: tuple[str, ...]) -> None:
        def visit(candidate: SemanticExpr) -> None:
            if not isinstance(candidate, (CastExprS, TypeTestExprS)):
                return
            if not is_reference_type_name(candidate.target_type_name):
                return
            if declaration_tables.interface_descriptor_symbol_for_type_name(module_path, candidate.target_type_name):
                return
            names.add(candidate.target_type_name)

        walk_expression(expr, visit)

    for fn in program.functions:
        if fn.body is None:
            continue
        walk_block_expressions(fn.body, lambda expr, module_path=fn.function_id.module_path: _collect_expr(expr, module_path))

    for cls in program.classes:
        for field in cls.fields:
            if field.initializer is not None:
                _collect_expr(field.initializer, cls.class_id.module_path)
        for method in cls.methods:
            walk_block_expressions(
                method.body,
                lambda expr, module_path=method.method_id.module_path: _collect_expr(expr, module_path),
            )

    return names


def _qualified_class_type_name(class_id: ClassId) -> str:
    return f"{'.'.join(class_id.module_path)}::{class_id.name}"


def _qualified_interface_type_name(interface_id: InterfaceId) -> str:
    return f"{'.'.join(interface_id.module_path)}::{interface_id.name}"