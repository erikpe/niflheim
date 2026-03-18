from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.symbols as codegen_symbols

from compiler.codegen.generator import CodeGenerator
from compiler.codegen.emitter_module import generate_module
from compiler.codegen.model import ConstructorLayout
from compiler.codegen_linker import CodegenProgram
from compiler.semantic_symbols import ClassId, ConstructorId, FunctionId, MethodId


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


class ProgramGenerator(CodeGenerator):
    def __init__(self, program: CodegenProgram) -> None:
        super().__init__()
        self.program = program
        self.declaration_tables: DeclarationTables | None = None

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
        )
        return self.declaration_tables

    def generate(self) -> str:
        self.build_declaration_tables()
        return generate_module(self, self.program)


def emit_program(program: CodegenProgram) -> str:
    return ProgramGenerator(program).generate()
