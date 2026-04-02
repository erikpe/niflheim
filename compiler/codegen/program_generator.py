from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.metadata import TypeMetadata, build_type_metadata, qualified_interface_type_name
from compiler.codegen.generator import CodeGenerator, CodegenOptions
from compiler.codegen.emitter_module import generate_module
from compiler.codegen.model import ConstructorLayout
from compiler.resolver import ModulePath
from compiler.semantic.lowered_ir import LoweredLinkedSemanticProgram
from compiler.semantic.symbols import ClassId, ConstructorId, InterfaceId, InterfaceMethodId, MethodId
from compiler.semantic.types import SemanticTypeRef


@dataclass(frozen=True)
class DeclarationTables:
    _method_labels_by_id: dict[MethodId, str]
    _constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout]
    _class_field_offsets_by_id: dict[tuple[ClassId, str], int]
    _interface_descriptor_symbols_by_id: dict[InterfaceId, str]
    _interface_method_slots_by_id: dict[InterfaceMethodId, int]

    def method_label(self, method_id: MethodId) -> str | None:
        return self._method_labels_by_id.get(method_id)

    def constructor_layout(self, constructor_id: ConstructorId) -> ConstructorLayout | None:
        return self._constructor_layouts_by_id.get(constructor_id)

    def constructor_label(self, constructor_id: ConstructorId) -> str | None:
        layout = self.constructor_layout(constructor_id)
        return layout.label if layout is not None else None

    def class_field_offset(self, class_id: ClassId, field_name: str) -> int | None:
        return self._class_field_offsets_by_id.get((class_id, field_name))

    def interface_descriptor_symbol(self, interface_id: InterfaceId) -> str | None:
        return self._interface_descriptor_symbols_by_id.get(interface_id)

    def interface_method_slot(self, method_id: InterfaceMethodId) -> int | None:
        return self._interface_method_slots_by_id.get(method_id)

    def interface_descriptor_symbol_for_type_name(
        self, current_module_path: ModulePath | None, type_name: str
    ) -> str | None:
        interface_id = _interface_id_from_type_name(current_module_path, type_name)
        if interface_id is None:
            return None
        return self.interface_descriptor_symbol(interface_id)

    def interface_descriptor_symbol_for_type_ref(self, type_ref: SemanticTypeRef) -> str | None:
        if type_ref.interface_id is None:
            return None
        return self.interface_descriptor_symbol(type_ref.interface_id)


def _interface_id_from_type_name(current_module_path: ModulePath | None, type_name: str) -> InterfaceId | None:
    if "::" in type_name:
        owner_dotted, interface_name = type_name.split("::", 1)
        return InterfaceId(module_path=tuple(owner_dotted.split(".")), name=interface_name)
    if current_module_path is None:
        return None
    return InterfaceId(module_path=current_module_path, name=type_name)


class ProgramGenerator(CodeGenerator):
    def __init__(self, program: LoweredLinkedSemanticProgram, *, options: CodegenOptions | None = None) -> None:
        super().__init__(options=options)
        self.program = program
        self.declaration_tables: DeclarationTables | None = None
        self.type_metadata: TypeMetadata | None = None

    def build_declaration_tables(self) -> DeclarationTables:
        if self.declaration_tables is not None:
            return self.declaration_tables

        method_labels_by_id: dict[MethodId, str] = {}
        constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout] = {}
        class_field_offsets_by_id: dict[tuple[ClassId, str], int] = {}
        interface_descriptor_symbols_by_id: dict[InterfaceId, str] = {}
        interface_method_slots_by_id: dict[InterfaceMethodId, int] = {}

        for module in self.program.ordered_modules:
            for interface in module.interfaces:
                qualified_name = qualified_interface_type_name(interface.interface_id)
                interface_descriptor_symbols_by_id[interface.interface_id] = codegen_symbols.mangle_interface_symbol(
                    qualified_name
                )
                for slot_index, method in enumerate(interface.methods):
                    interface_method_slots_by_id[method.method_id] = slot_index

        for cls in self.program.classes:
            class_name = cls.class_id.name
            for constructor in cls.constructors:
                constructor_id = constructor.constructor_id
                constructor_label = codegen_symbols.mangle_constructor_symbol(class_name, constructor_id.ordinal)
                constructor_layouts_by_id[constructor_id] = ConstructorLayout(
                    class_name=class_name,
                    label=constructor_label,
                    type_symbol=codegen_symbols.mangle_type_symbol(class_name),
                    payload_bytes=len(cls.fields) * 8,
                    field_names=[field.name for field in cls.fields],
                    param_names=[param.name for param in constructor.params],
                    param_field_names=[field.name for field in cls.fields if field.initializer is None]
                    if constructor.body is None
                    else [],
                )

            for field_index, field in enumerate(cls.fields):
                field_key = (cls.class_id, field.name)
                class_field_offsets_by_id[field_key] = 24 + (8 * field_index)

            for method in cls.methods:
                method_labels_by_id[method.method_id] = codegen_symbols.mangle_method_symbol(
                    class_name, method.method_id.name
                )

        self.declaration_tables = DeclarationTables(
            _method_labels_by_id=method_labels_by_id,
            _constructor_layouts_by_id=constructor_layouts_by_id,
            _class_field_offsets_by_id=class_field_offsets_by_id,
            _interface_descriptor_symbols_by_id=interface_descriptor_symbols_by_id,
            _interface_method_slots_by_id=interface_method_slots_by_id,
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


def emit_program(program: LoweredLinkedSemanticProgram, *, options: CodegenOptions | None = None) -> str:
    return ProgramGenerator(program, options=options).generate()
