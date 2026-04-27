from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from compiler.backend.ir import BackendCastInst, BackendDataId, BackendProgram, BackendTypeTestInst
from compiler.backend.ir._ordering import data_blob_sort_key
from compiler.backend.program.class_hierarchy import BackendClassHierarchyIndex
from compiler.backend.program.symbols import (
    BackendProgramSymbolTable,
    mangle_interface_method_table_symbol,
    mangle_type_name_symbol,
    mangle_type_symbol,
    qualified_class_name,
)
from compiler.semantic.types import (
    semantic_type_canonical_name,
    semantic_type_display_name,
    semantic_type_is_interface,
    semantic_type_is_reference,
)


@dataclass(frozen=True, slots=True)
class InterfaceMetadataRecord:
    interface_id: object
    display_name: str
    descriptor_symbol: str
    name_symbol: str
    slot_index: int
    method_count: int


@dataclass(frozen=True, slots=True)
class InterfaceMethodTableMetadataRecord:
    interface_id: object
    descriptor_symbol: str
    display_name: str
    method_count: int
    method_table_symbol: str
    method_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClassMetadataRecord:
    class_id: object
    qualified_type_name: str
    display_name: str
    aliases: tuple[str, ...]
    type_symbol: str
    type_name_symbol: str
    superclass_symbol: str | None
    pointer_offsets_symbol: str | None
    pointer_offsets: tuple[int, ...]
    interface_tables_symbol: str | None
    interface_table_slot_count: int
    interface_table_entries: tuple[str | None, ...]
    interface_method_tables: tuple[InterfaceMethodTableMetadataRecord, ...]
    class_vtable_symbol: str | None
    class_vtable_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExtraRuntimeTypeRecord:
    canonical_type_name: str
    display_name: str
    aliases: tuple[str, ...]
    type_symbol: str
    type_name_symbol: str


@dataclass(frozen=True, slots=True)
class BackendDataBlobMetadataRecord:
    data_id: BackendDataId
    symbol: str
    alignment: int
    bytes_hex: str
    readonly: bool
    byte_length: int


@dataclass(frozen=True, slots=True)
class BackendProgramMetadata:
    classes: tuple[ClassMetadataRecord, ...]
    interfaces: tuple[InterfaceMetadataRecord, ...]
    extra_runtime_types: tuple[ExtraRuntimeTypeRecord, ...]
    data_blobs: tuple[BackendDataBlobMetadataRecord, ...]

    @property
    def extra_runtime_type_names(self) -> tuple[str, ...]:
        return tuple(record.canonical_type_name for record in self.extra_runtime_types)


def build_backend_program_metadata(
    program: BackendProgram,
    *,
    symbols: BackendProgramSymbolTable,
    class_hierarchy: BackendClassHierarchyIndex,
) -> BackendProgramMetadata:
    interface_records = tuple(
        InterfaceMetadataRecord(
            interface_id=interface_decl.interface_id,
            display_name=symbols.interface_symbols(interface_decl.interface_id).qualified_type_name,
            descriptor_symbol=symbols.interface_symbols(interface_decl.interface_id).descriptor_symbol,
            name_symbol=symbols.interface_symbols(interface_decl.interface_id).name_symbol,
            slot_index=slot_index,
            method_count=len(interface_decl.methods),
        )
        for slot_index, interface_decl in enumerate(program.interfaces)
    )
    interface_slot_count = len(interface_records)
    interface_decl_by_id = {interface_decl.interface_id: interface_decl for interface_decl in program.interfaces}

    reference_runtime_types = _collect_reference_runtime_types(program)
    reserved_class_alias_names = _reserved_class_alias_names(program)
    short_type_alias_counts = _short_type_alias_counts(program, reference_runtime_types, reserved_class_alias_names)

    class_records: list[ClassMetadataRecord] = []
    for class_decl in program.classes:
        class_symbols = symbols.class_symbols(class_decl.class_id)
        qualified_type_name = class_symbols.qualified_type_name
        pointer_offsets = class_hierarchy.pointer_offsets(class_decl.class_id)
        superclass_symbol = None
        if class_decl.superclass_id is not None:
            superclass_symbol = symbols.class_symbols(class_decl.superclass_id).type_symbol

        interface_method_tables: list[InterfaceMethodTableMetadataRecord] = []
        interface_table_entries: list[str | None] = [None] * interface_slot_count
        for interface_id in class_decl.implemented_interfaces:
            interface_decl = interface_decl_by_id[interface_id]
            interface_symbols = symbols.interface_symbols(interface_id)
            method_labels = tuple(
                symbols.callable(class_hierarchy.resolve_method_id(class_decl.class_id, method_id.name)).direct_call_symbol
                for method_id in interface_decl.methods
            )
            method_table_symbol = mangle_interface_method_table_symbol(class_decl.class_id, interface_id)
            interface_slot_index = next(
                record.slot_index for record in interface_records if record.interface_id == interface_id
            )
            interface_table_entries[interface_slot_index] = method_table_symbol
            interface_method_tables.append(
                InterfaceMethodTableMetadataRecord(
                    interface_id=interface_id,
                    descriptor_symbol=interface_symbols.descriptor_symbol,
                    display_name=interface_symbols.qualified_type_name,
                    method_count=len(interface_decl.methods),
                    method_table_symbol=method_table_symbol,
                    method_labels=method_labels,
                )
            )

        class_vtable_labels = tuple(
            symbols.callable(slot.selected_method_id).direct_call_symbol
            for slot in class_hierarchy.effective_virtual_slots(class_decl.class_id)
        )
        class_records.append(
            ClassMetadataRecord(
                class_id=class_decl.class_id,
                qualified_type_name=qualified_type_name,
                display_name=qualified_type_name if qualified_type_name != class_decl.class_id.name else class_decl.class_id.name,
                aliases=_class_aliases(class_decl.class_id, short_type_alias_counts),
                type_symbol=class_symbols.type_symbol,
                type_name_symbol=class_symbols.type_name_symbol,
                superclass_symbol=superclass_symbol,
                pointer_offsets_symbol=class_symbols.pointer_offsets_symbol if pointer_offsets else None,
                pointer_offsets=pointer_offsets,
                interface_tables_symbol=class_symbols.interface_tables_symbol if interface_slot_count > 0 else None,
                interface_table_slot_count=interface_slot_count,
                interface_table_entries=tuple(interface_table_entries),
                interface_method_tables=tuple(interface_method_tables),
                class_vtable_symbol=class_symbols.class_vtable_symbol if class_vtable_labels else None,
                class_vtable_labels=class_vtable_labels,
            )
        )

    extra_runtime_types = tuple(
        ExtraRuntimeTypeRecord(
            canonical_type_name=canonical_name,
            display_name=display_name,
            aliases=_extra_runtime_type_aliases(
                canonical_name,
                display_name,
                reserved_class_alias_names,
                short_type_alias_counts,
            ),
            type_symbol=mangle_type_symbol(canonical_name),
            type_name_symbol=mangle_type_name_symbol(canonical_name),
        )
        for canonical_name, display_name in sorted(reference_runtime_types.items(), key=lambda item: item[0])
        if canonical_name not in reserved_class_alias_names
    )

    data_blob_records = tuple(
        BackendDataBlobMetadataRecord(
            data_id=blob.data_id,
            symbol=symbols.data_blob_symbols(blob.data_id).symbol,
            alignment=blob.alignment,
            bytes_hex=blob.bytes_hex,
            readonly=blob.readonly,
            byte_length=len(blob.bytes_hex) // 2,
        )
        for blob in sorted(program.data_blobs, key=data_blob_sort_key)
    )

    return BackendProgramMetadata(
        classes=tuple(class_records),
        interfaces=interface_records,
        extra_runtime_types=extra_runtime_types,
        data_blobs=data_blob_records,
    )


def _reserved_class_alias_names(program: BackendProgram) -> set[str]:
    reserved_names: set[str] = set()
    for class_decl in program.classes:
        reserved_names.add(class_decl.class_id.name)
        reserved_names.add(qualified_class_name(class_decl.class_id))
    return reserved_names


def _short_type_alias_counts(
    program: BackendProgram,
    reference_runtime_types: dict[str, str],
    reserved_class_alias_names: set[str],
) -> Counter[str]:
    counts = Counter(class_decl.class_id.name for class_decl in program.classes)
    for canonical_name, display_name in reference_runtime_types.items():
        if canonical_name in reserved_class_alias_names:
            continue
        if display_name == "" or display_name == canonical_name:
            continue
        counts[display_name] += 1
    return counts


def _class_aliases(class_id, short_type_alias_counts: Counter[str]) -> tuple[str, ...]:
    aliases: list[str] = []
    if short_type_alias_counts[class_id.name] == 1:
        aliases.append(class_id.name)
    aliases.append(qualified_class_name(class_id))
    return tuple(aliases)


def _extra_runtime_type_aliases(
    canonical_name: str,
    display_name: str,
    reserved_class_alias_names: set[str],
    short_type_alias_counts: Counter[str],
) -> tuple[str, ...]:
    aliases: list[str] = []
    if (
        display_name != ""
        and display_name != canonical_name
        and display_name not in reserved_class_alias_names
        and short_type_alias_counts[display_name] == 1
    ):
        aliases.append(display_name)
    aliases.append(canonical_name)
    return tuple(aliases)


def _collect_reference_runtime_types(program: BackendProgram) -> dict[str, str]:
    names: dict[str, str] = {}
    for callable_decl in program.callables:
        for block in callable_decl.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, (BackendCastInst, BackendTypeTestInst)):
                    target_type_ref = instruction.target_type_ref
                    if not semantic_type_is_reference(target_type_ref):
                        continue
                    if semantic_type_is_interface(target_type_ref):
                        continue
                    names[semantic_type_canonical_name(target_type_ref)] = semantic_type_display_name(target_type_ref)
    return names


__all__ = [
    "BackendDataBlobMetadataRecord",
    "BackendProgramMetadata",
    "ClassMetadataRecord",
    "ExtraRuntimeTypeRecord",
    "InterfaceMetadataRecord",
    "InterfaceMethodTableMetadataRecord",
    "build_backend_program_metadata",
]