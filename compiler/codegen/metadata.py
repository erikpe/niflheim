from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from compiler.codegen.class_hierarchy import ClassHierarchyIndex
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.walk import walk_block_expressions, walk_expression
from compiler.semantic.display import semantic_type_display_name_relative
from compiler.semantic.ir import *
from compiler.semantic.lowered_ir import LoweredLinkedSemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceId, MethodId
from compiler.semantic.types import semantic_type_canonical_name, semantic_type_is_interface, semantic_type_is_reference

if TYPE_CHECKING:
    from compiler.codegen.program_generator import DeclarationTables


@dataclass(frozen=True)
class InterfaceMetadataRecord:
    interface_id: InterfaceId
    display_name: str
    descriptor_symbol: str
    slot_index: int
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
    superclass_symbol: str | None
    pointer_offsets_symbol: str | None
    pointer_offsets: tuple[int, ...]
    interface_tables_symbol: str | None
    interface_table_slot_count: int
    interface_table_entries: tuple[str | None, ...]
    interface_impls_symbol: str | None
    interface_impls: tuple[InterfaceImplMetadataRecord, ...]
    class_vtable_symbol: str | None
    class_vtable_labels: tuple[str, ...]


@dataclass(frozen=True)
class ExtraRuntimeTypeRecord:
    canonical_type_name: str
    display_name: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class TypeMetadata:
    classes: tuple[ClassMetadataRecord, ...]
    interfaces: tuple[InterfaceMetadataRecord, ...]
    extra_runtime_types: tuple[ExtraRuntimeTypeRecord, ...]

    @property
    def extra_runtime_type_names(self) -> tuple[str, ...]:
        return tuple(record.canonical_type_name for record in self.extra_runtime_types)


def build_type_metadata(
    program: LoweredLinkedSemanticProgram,
    declaration_tables: DeclarationTables,
    class_hierarchy: ClassHierarchyIndex,
) -> TypeMetadata:
    interface_decls = [interface for module in program.ordered_modules for interface in module.interfaces]
    interfaces_by_id = {interface.interface_id: interface for interface in interface_decls}

    interface_records = tuple(
        InterfaceMetadataRecord(
            interface_id=interface.interface_id,
            display_name=qualified_interface_type_name(interface.interface_id),
            descriptor_symbol=declaration_tables.interface_descriptor_symbol(interface.interface_id),
            slot_index=_require_interface_slot(declaration_tables, interface.interface_id),
            method_count=len(interface.methods),
        )
        for interface in interface_decls
    )
    interface_slot_count = len(interface_records)

    class_records: list[ClassMetadataRecord] = []
    class_alias_names: set[str] = set()
    for cls in program.classes:
        qualified_type_name = qualified_class_type_name(cls.class_id)
        aliases = [cls.class_id.name]
        if qualified_type_name != cls.class_id.name:
            aliases.append(qualified_type_name)
        class_alias_names.update(aliases)

        display_name = qualified_type_name if qualified_type_name != cls.class_id.name else cls.class_id.name
        superclass_symbol = None
        if cls.superclass_id is not None:
            superclass_symbol = codegen_symbols.mangle_type_symbol(qualified_class_type_name(cls.superclass_id))

        pointer_offsets = class_hierarchy.pointer_offsets(cls.class_id)
        pointer_offsets_symbol = None
        if pointer_offsets:
            pointer_offsets_symbol = codegen_symbols.mangle_type_pointer_offsets_symbol(qualified_type_name)

        interface_impls: list[InterfaceImplMetadataRecord] = []
        interface_table_entries: list[str | None] = [None] * interface_slot_count
        interface_tables_symbol: str | None = None
        interface_impls_symbol: str | None = None
        if interface_slot_count > 0:
            interface_tables_symbol = codegen_symbols.mangle_class_interface_tables_symbol(qualified_type_name)
        if cls.implemented_interfaces:
            interface_impls_symbol = codegen_symbols.mangle_class_interface_impls_symbol(qualified_type_name)
            for interface_id in cls.implemented_interfaces:
                interface = interfaces_by_id[interface_id]
                interface_display_name = qualified_interface_type_name(interface_id)
                method_labels: list[str] = []
                for interface_method in interface.methods:
                    implementing_method_id = class_hierarchy.resolve_method_id(cls.class_id, interface_method.method_id.name)
                    method_label = declaration_tables.method_label(implementing_method_id)
                    if method_label is None:
                        raise ValueError(
                            f"Missing method label for interface implementation '{implementing_method_id.class_name}.{implementing_method_id.name}'"
                        )
                    method_labels.append(method_label)
                method_table_symbol = codegen_symbols.mangle_interface_method_table_symbol(
                    qualified_type_name, interface_display_name
                )
                interface_table_entries[_require_interface_slot(declaration_tables, interface_id)] = method_table_symbol
                interface_impls.append(
                    InterfaceImplMetadataRecord(
                        interface_id=interface_id,
                        descriptor_symbol=declaration_tables.interface_descriptor_symbol(interface_id),
                        display_name=interface_display_name,
                        method_count=len(interface.methods),
                        method_table_symbol=method_table_symbol,
                        method_labels=tuple(method_labels),
                    )
                )

        class_vtable_labels: list[str] = []
        for virtual_slot in class_hierarchy.effective_virtual_slots(cls.class_id):
            method_label = declaration_tables.method_label(virtual_slot.selected_method_id)
            if method_label is None:
                raise ValueError(
                    f"Missing method label for virtual slot '{virtual_slot.selected_method_id.class_name}.{virtual_slot.selected_method_id.name}'"
                )
            class_vtable_labels.append(method_label)

        class_vtable_symbol = None
        if class_vtable_labels:
            class_vtable_symbol = declaration_tables.class_vtable_symbol(cls.class_id)
            if class_vtable_symbol is None:
                raise ValueError(f"Missing class vtable symbol for '{qualified_type_name}'")

        class_records.append(
            ClassMetadataRecord(
                class_id=cls.class_id,
                qualified_type_name=qualified_type_name,
                display_name=display_name,
                aliases=tuple(aliases),
                superclass_symbol=superclass_symbol,
                pointer_offsets_symbol=pointer_offsets_symbol,
                pointer_offsets=pointer_offsets,
                interface_tables_symbol=interface_tables_symbol,
                interface_table_slot_count=interface_slot_count,
                interface_table_entries=tuple(interface_table_entries),
                interface_impls_symbol=interface_impls_symbol,
                interface_impls=tuple(interface_impls),
                class_vtable_symbol=class_vtable_symbol,
                class_vtable_labels=tuple(class_vtable_labels),
            )
        )

    extra_runtime_types = tuple(
        ExtraRuntimeTypeRecord(
            canonical_type_name=canonical_name,
            display_name=display_name,
            aliases=tuple(
                alias
                for alias in (display_name, canonical_name)
                if alias not in class_alias_names and alias != ""
            ),
        )
        for canonical_name, display_name in sorted(
            _collect_reference_cast_type_names(program, declaration_tables).items(), key=lambda item: item[0]
        )
        if canonical_name not in class_alias_names
    )

    return TypeMetadata(
        classes=tuple(class_records), interfaces=interface_records, extra_runtime_types=extra_runtime_types
    )


def _require_interface_slot(declaration_tables: DeclarationTables, interface_id: InterfaceId) -> int:
    slot_index = declaration_tables.interface_slot(interface_id)
    if slot_index is None:
        raise ValueError(f"Missing interface slot for '{qualified_interface_type_name(interface_id)}'")
    return slot_index


def _collect_reference_cast_type_names(
    program: LoweredLinkedSemanticProgram, declaration_tables: DeclarationTables
) -> dict[str, str]:
    names: dict[str, str] = {}

    def _collect_expr(expr: SemanticExpr, module_path: tuple[str, ...]) -> None:
        def visit(candidate: SemanticExpr) -> None:
            if not isinstance(candidate, (CastExprS, TypeTestExprS)):
                return
            if not codegen_types.is_reference_type_ref(candidate.target_type_ref):
                return
            if semantic_type_is_interface(candidate.target_type_ref):
                return
            names[semantic_type_canonical_name(candidate.target_type_ref)] = semantic_type_display_name_relative(
                module_path, candidate.target_type_ref
            )

        walk_expression(expr, visit)

    for fn in program.functions:
        if fn.body is None:
            continue
        walk_block_expressions(
            fn.body, lambda expr, module_path=fn.function_id.module_path: _collect_expr(expr, module_path)
        )

    for cls in program.classes:
        for field in cls.fields:
            if field.initializer is not None:
                _collect_expr(field.initializer, cls.class_id.module_path)
        for method in cls.methods:
            walk_block_expressions(
                method.body, lambda expr, module_path=method.method_id.module_path: _collect_expr(expr, module_path)
            )

    return names


def qualified_class_type_name(class_id: ClassId) -> str:
    return f"{'.'.join(class_id.module_path)}::{class_id.name}"


def qualified_interface_type_name(interface_id: InterfaceId) -> str:
    return f"{'.'.join(interface_id.module_path)}::{interface_id.name}"
