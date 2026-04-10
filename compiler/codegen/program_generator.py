from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.class_hierarchy import ClassHierarchyIndex
from compiler.codegen.metadata import TypeMetadata, build_type_metadata, qualified_class_type_name, qualified_interface_type_name
from compiler.codegen.generator import CodeGenerator, CodegenOptions
from compiler.codegen.emitter_module import generate_module
from compiler.codegen.model import ConstructorLayout
from compiler.resolver import ModulePath
from compiler.semantic.lowered_ir import LoweredLinkedSemanticProgram
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, InterfaceMethodId, MethodId
from compiler.semantic.types import SemanticTypeRef


@dataclass(frozen=True)
class DeclarationTables:
    _function_labels_by_id: dict[FunctionId, str]
    _method_labels_by_id: dict[MethodId, str]
    _constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout]
    _class_field_offsets_by_id: dict[tuple[ClassId, str], int]
    _class_vtable_symbols_by_id: dict[ClassId, str]
    _class_virtual_slot_indices_by_key: dict[tuple[ClassId, ClassId, str], int]
    _interface_descriptor_symbols_by_id: dict[InterfaceId, str]
    _interface_slots_by_id: dict[InterfaceId, int]
    _interface_method_slots_by_id: dict[InterfaceMethodId, int]

    def function_label(self, function_id: FunctionId) -> str | None:
        return self._function_labels_by_id.get(function_id)

    def method_label(self, method_id: MethodId) -> str | None:
        return self._method_labels_by_id.get(method_id)

    def constructor_layout(self, constructor_id: ConstructorId) -> ConstructorLayout | None:
        return self._constructor_layouts_by_id.get(constructor_id)

    def constructor_label(self, constructor_id: ConstructorId) -> str | None:
        layout = self.constructor_layout(constructor_id)
        return layout.label if layout is not None else None

    def constructor_init_label(self, constructor_id: ConstructorId) -> str | None:
        layout = self.constructor_layout(constructor_id)
        return layout.init_label if layout is not None else None

    def class_field_offset(self, class_id: ClassId, field_name: str) -> int | None:
        return self._class_field_offsets_by_id.get((class_id, field_name))

    def class_vtable_symbol(self, class_id: ClassId) -> str | None:
        return self._class_vtable_symbols_by_id.get(class_id)

    def class_virtual_slot_index(self, class_id: ClassId, slot_owner_class_id: ClassId, method_name: str) -> int | None:
        return self._class_virtual_slot_indices_by_key.get((class_id, slot_owner_class_id, method_name))

    def interface_descriptor_symbol(self, interface_id: InterfaceId) -> str | None:
        return self._interface_descriptor_symbols_by_id.get(interface_id)

    def interface_slot(self, interface_id: InterfaceId) -> int | None:
        return self._interface_slots_by_id.get(interface_id)

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
        self.class_hierarchy: ClassHierarchyIndex | None = None
        self.type_metadata: TypeMetadata | None = None

    def build_class_hierarchy(self) -> ClassHierarchyIndex:
        if self.class_hierarchy is None:
            self.class_hierarchy = ClassHierarchyIndex(self.program)
        return self.class_hierarchy

    def build_declaration_tables(self) -> DeclarationTables:
        if self.declaration_tables is not None:
            return self.declaration_tables

        class_hierarchy = self.build_class_hierarchy()

        function_labels_by_id: dict[FunctionId, str] = {}
        method_labels_by_id: dict[MethodId, str] = {}
        constructor_layouts_by_id: dict[ConstructorId, ConstructorLayout] = {}
        class_field_offsets_by_id: dict[tuple[ClassId, str], int] = {}
        class_vtable_symbols_by_id: dict[ClassId, str] = {}
        class_virtual_slot_indices_by_key: dict[tuple[ClassId, ClassId, str], int] = {}
        interface_descriptor_symbols_by_id: dict[InterfaceId, str] = {}
        interface_slots_by_id: dict[InterfaceId, int] = {}
        interface_method_slots_by_id: dict[InterfaceMethodId, int] = {}
        emitted_symbols: dict[str, str] = {}

        def register_emitted_symbol(symbol: str, owner: str) -> str:
            existing_owner = emitted_symbols.get(symbol)
            if existing_owner is not None and existing_owner != owner:
                raise ValueError(
                    f"Conflicting emitted symbol '{symbol}' for {owner} (already used by {existing_owner})"
                )
            emitted_symbols[symbol] = owner
            return symbol

        for function in self.program.functions:
            if function.is_extern:
                function_labels_by_id[function.function_id] = register_emitted_symbol(
                    function.function_id.name,
                    f"function {'.'.join(function.function_id.module_path)}::{function.function_id.name}",
                )
                continue
            function_labels_by_id[function.function_id] = register_emitted_symbol(
                codegen_symbols.mangle_function_symbol(
                    function.function_id.module_path,
                    function.function_id.name,
                ),
                f"function {'.'.join(function.function_id.module_path)}::{function.function_id.name}",
            )

        next_interface_slot = 0
        for module in self.program.ordered_modules:
            for interface in module.interfaces:
                qualified_name = qualified_interface_type_name(interface.interface_id)
                interface_descriptor_symbols_by_id[interface.interface_id] = register_emitted_symbol(
                    codegen_symbols.mangle_interface_symbol(qualified_name),
                    f"interface {qualified_name}",
                )
                interface_slots_by_id[interface.interface_id] = next_interface_slot
                next_interface_slot += 1
                for slot_index, method in enumerate(interface.methods):
                    interface_method_slots_by_id[method.method_id] = slot_index

        constructor_param_counts = {
            constructor.constructor_id: len(constructor.params)
            for cls in self.program.classes
            for constructor in cls.constructors
        }

        for cls in self.program.classes:
            class_name = cls.class_id.name
            qualified_type_name = qualified_class_type_name(cls.class_id)
            class_vtable_symbols_by_id[cls.class_id] = register_emitted_symbol(
                codegen_symbols.mangle_class_vtable_symbol(qualified_type_name),
                f"class vtable {qualified_type_name}",
            )
            for constructor in cls.constructors:
                constructor_id = constructor.constructor_id
                constructor_label = register_emitted_symbol(
                    codegen_symbols.mangle_constructor_symbol(qualified_type_name, constructor_id.ordinal),
                    f"constructor {qualified_type_name}#{constructor_id.ordinal}",
                )
                constructor_init_label = register_emitted_symbol(
                    codegen_symbols.mangle_constructor_init_symbol(qualified_type_name, constructor_id.ordinal),
                    f"constructor init {qualified_type_name}#{constructor_id.ordinal}",
                )
                constructor_layouts_by_id[constructor_id] = ConstructorLayout(
                    class_name=class_name,
                    label=constructor_label,
                    init_label=constructor_init_label,
                    type_symbol=codegen_symbols.mangle_type_symbol(qualified_type_name),
                    payload_bytes=class_hierarchy.payload_bytes(cls.class_id),
                    field_names=[field.name for field in cls.fields],
                    param_names=[param.name for param in constructor.params],
                    param_field_names=[field.name for field in cls.fields if field.initializer is None]
                    if constructor.body is None
                    else [],
                    super_param_count=(
                        0
                        if constructor.super_constructor_id is None
                        else constructor_param_counts[constructor.super_constructor_id]
                    ),
                )

            for field_slot in class_hierarchy.effective_field_slots(cls.class_id):
                field_key = (field_slot.owner_class_id, field_slot.field.name)
                existing_offset = class_field_offsets_by_id.get(field_key)
                if existing_offset is not None and existing_offset != field_slot.offset:
                    raise ValueError(
                        f"Conflicting field offsets for '{field_slot.owner_class_id.name}.{field_slot.field.name}'"
                    )
                class_field_offsets_by_id[field_key] = field_slot.offset

            for virtual_slot in class_hierarchy.effective_virtual_slots(cls.class_id):
                class_virtual_slot_indices_by_key[
                    (cls.class_id, virtual_slot.slot_owner_class_id, virtual_slot.method_name)
                ] = virtual_slot.slot_index

            for method in cls.methods:
                method_labels_by_id[method.method_id] = register_emitted_symbol(
                    codegen_symbols.mangle_method_symbol(qualified_type_name, method.method_id.name),
                    f"method {qualified_type_name}.{method.method_id.name}",
                )

        self.declaration_tables = DeclarationTables(
            _function_labels_by_id=function_labels_by_id,
            _method_labels_by_id=method_labels_by_id,
            _constructor_layouts_by_id=constructor_layouts_by_id,
            _class_field_offsets_by_id=class_field_offsets_by_id,
            _class_vtable_symbols_by_id=class_vtable_symbols_by_id,
            _class_virtual_slot_indices_by_key=class_virtual_slot_indices_by_key,
            _interface_descriptor_symbols_by_id=interface_descriptor_symbols_by_id,
            _interface_slots_by_id=interface_slots_by_id,
            _interface_method_slots_by_id=interface_method_slots_by_id,
        )
        return self.declaration_tables

    def build_type_metadata(self) -> TypeMetadata:
        if self.type_metadata is not None:
            return self.type_metadata

        class_hierarchy = self.build_class_hierarchy()
        declaration_tables = self.build_declaration_tables()
        self.type_metadata = build_type_metadata(self.program, declaration_tables, class_hierarchy)
        return self.type_metadata

    def generate(self) -> str:
        declaration_tables = self.build_declaration_tables()
        type_metadata = self.build_type_metadata()
        return generate_module(self, self.program, declaration_tables, type_metadata)


def emit_program(program: LoweredLinkedSemanticProgram, *, options: CodegenOptions | None = None) -> str:
    return ProgramGenerator(program, options=options).generate()
