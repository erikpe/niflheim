from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.metadata import TypeMetadata, build_type_metadata
from compiler.codegen.generator import CodeGenerator
from compiler.codegen.emitter_module import generate_module
from compiler.codegen.linker import CodegenProgram
from compiler.codegen.model import ConstructorLayout
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, InterfaceMethodId, MethodId


@dataclass(frozen=True)
class DeclarationTables:
    method_labels_by_id: dict[MethodId, str]
    method_return_types_by_id: dict[MethodId, str]
    method_is_static_by_id: dict[MethodId, bool]
    function_return_types_by_id: dict[FunctionId, str]
    constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout]
    constructor_labels_by_id: dict[ConstructorId, str]
    class_field_offsets_by_id: dict[tuple[ClassId, str], int]
    class_field_type_names_by_id: dict[tuple[ClassId, str], str]
    interface_descriptor_symbols_by_id: dict[InterfaceId, str]
    interface_method_slots_by_id: dict[InterfaceMethodId, int]
    local_interface_ids_by_module: dict[ModulePath, dict[str, InterfaceId]]

    def interface_descriptor_symbol_for_type_name(
        self, current_module_path: ModulePath | None, type_name: str
    ) -> str | None:
        interface_id = _interface_id_from_type_name(current_module_path, type_name)
        if interface_id is None:
            return None
        return self.interface_descriptor_symbols_by_id.get(interface_id)


def _interface_id_from_type_name(current_module_path: ModulePath | None, type_name: str) -> InterfaceId | None:
    if "::" in type_name:
        owner_dotted, interface_name = type_name.split("::", 1)
        return InterfaceId(module_path=tuple(owner_dotted.split(".")), name=interface_name)
    if current_module_path is None:
        return None
    return InterfaceId(module_path=current_module_path, name=type_name)


class ProgramGenerator(CodeGenerator):
    def __init__(self, program: CodegenProgram) -> None:
        super().__init__()
        self.program = program
        self.declaration_tables: DeclarationTables | None = None
        self.type_metadata: TypeMetadata | None = None

    def build_declaration_tables(self) -> DeclarationTables:
        if self.declaration_tables is not None:
            return self.declaration_tables

        method_labels_by_id: dict[MethodId, str] = {}
        method_return_types_by_id: dict[MethodId, str] = {}
        method_is_static_by_id: dict[MethodId, bool] = {}
        function_return_types_by_id: dict[FunctionId, str] = {}
        constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout] = {}
        constructor_labels_by_id: dict[ConstructorId, str] = {}
        class_field_offsets_by_id: dict[tuple[ClassId, str], int] = {}
        class_field_type_names_by_id: dict[tuple[ClassId, str], str] = {}
        interface_descriptor_symbols_by_id: dict[InterfaceId, str] = {}
        interface_method_slots_by_id: dict[InterfaceMethodId, int] = {}
        local_interface_ids_by_module: dict[ModulePath, dict[str, InterfaceId]] = {}

        for module in self.program.ordered_modules:
            local_interface_ids_by_module[module.module_path] = {
                interface.interface_id.name: interface.interface_id for interface in module.interfaces
            }
            for interface in module.interfaces:
                qualified_name = _qualified_interface_type_name(interface.interface_id)
                interface_descriptor_symbols_by_id[interface.interface_id] = codegen_symbols.mangle_interface_symbol(
                    qualified_name
                )
                for slot_index, method in enumerate(interface.methods):
                    interface_method_slots_by_id[method.method_id] = slot_index

        for cls in self.program.classes:
            class_name = cls.class_id.name
            constructor_id = ConstructorId(module_path=cls.class_id.module_path, class_name=class_name)
            constructor_label = codegen_symbols.mangle_constructor_symbol(class_name)
            constructor_layouts_by_id[constructor_id] = ConstructorLayout(
                class_name=class_name,
                label=constructor_label,
                type_symbol=codegen_symbols.mangle_type_symbol(class_name),
                payload_bytes=len(cls.fields) * 8,
                field_names=[field.name for field in cls.fields],
                param_field_names=[field.name for field in cls.fields if field.initializer is None],
            )
            constructor_labels_by_id[constructor_id] = constructor_label

            for field_index, field in enumerate(cls.fields):
                field_key = (cls.class_id, field.name)
                class_field_offsets_by_id[field_key] = 24 + (8 * field_index)
                class_field_type_names_by_id[field_key] = field.type_name

            for method in cls.methods:
                method_labels_by_id[method.method_id] = codegen_symbols.mangle_method_symbol(
                    class_name, method.method_id.name
                )
                method_return_types_by_id[method.method_id] = method.return_type_name
                method_is_static_by_id[method.method_id] = method.is_static

        for fn in self.program.functions:
            function_return_types_by_id[fn.function_id] = fn.return_type_name

        self.declaration_tables = DeclarationTables(
            method_labels_by_id=method_labels_by_id,
            method_return_types_by_id=method_return_types_by_id,
            method_is_static_by_id=method_is_static_by_id,
            function_return_types_by_id=function_return_types_by_id,
            constructor_layouts_by_id=constructor_layouts_by_id,
            constructor_labels_by_id=constructor_labels_by_id,
            class_field_offsets_by_id=class_field_offsets_by_id,
            class_field_type_names_by_id=class_field_type_names_by_id,
            interface_descriptor_symbols_by_id=interface_descriptor_symbols_by_id,
            interface_method_slots_by_id=interface_method_slots_by_id,
            local_interface_ids_by_module=local_interface_ids_by_module,
        )
        return self.declaration_tables

    def build_type_metadata(self) -> TypeMetadata:
        if self.type_metadata is not None:
            return self.type_metadata

        declaration_tables = self.build_declaration_tables()
        self.type_metadata = build_type_metadata(self.program, declaration_tables)
        return self.type_metadata

    def generate(self) -> str:
        declaration_tables = self.build_declaration_tables()
        type_metadata = self.build_type_metadata()
        return generate_module(self, self.program, declaration_tables, type_metadata)


def emit_program(program: CodegenProgram) -> str:
    return ProgramGenerator(program).generate()


def _qualified_interface_type_name(interface_id: InterfaceId) -> str:
    return f"{'.'.join(interface_id.module_path)}::{interface_id.name}"
