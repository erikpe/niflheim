"""Program-level backend lowering entrypoint for phase-2 PR1."""

from __future__ import annotations

from dataclasses import dataclass, field

from compiler.backend.ir import model as ir_model
from compiler.backend.ir._ordering import callable_id_sort_key, class_id_sort_key, interface_id_sort_key, interface_method_id_sort_key
from compiler.backend.ir.verify import verify_backend_program
from compiler.backend.lowering.functions import (
    build_callable_surface_by_id,
    lower_constructor_callable,
    lower_field_decl,
    lower_function_callable,
    lower_method_callable,
)
from compiler.semantic.ir import SemanticClass, SemanticInterface
from compiler.semantic.linker import LinkedSemanticProgram, require_main_function
from compiler.semantic.symbols import ClassId, FunctionId, InterfaceId


@dataclass
class ProgramLoweringContext:
    program: LinkedSemanticProgram
    interface_decl_by_id: dict[InterfaceId, ir_model.BackendInterfaceDecl] = field(default_factory=dict)
    class_decl_by_id: dict[ClassId, ir_model.BackendClassDecl] = field(default_factory=dict)
    callable_decl_by_id: dict[ir_model.BackendCallableId, ir_model.BackendCallableDecl] = field(default_factory=dict)
    data_blobs: list[ir_model.BackendDataBlob] = field(default_factory=list)
    next_data_ordinal: int = 0

    def allocate_data_id(self) -> ir_model.BackendDataId:
        data_id = ir_model.BackendDataId(ordinal=self.next_data_ordinal)
        self.next_data_ordinal += 1
        return data_id


def lower_to_backend_ir(program: LinkedSemanticProgram) -> ir_model.BackendProgram:
    require_main_function(program)
    context = ProgramLoweringContext(program=program)
    call_surface_by_id = build_callable_surface_by_id(program)

    interfaces = [_lower_interface_decl(interface) for interface in _iter_interfaces(program)]
    for interface_decl in interfaces:
        context.interface_decl_by_id[interface_decl.interface_id] = interface_decl

    classes = [_lower_class_decl(class_decl) for class_decl in program.classes]
    for class_decl in classes:
        context.class_decl_by_id[class_decl.class_id] = class_decl

    callable_decls = [
        lowered_callable.callable_decl
        for lowered_callable in _iter_lowered_callables(program, call_surface_by_id=call_surface_by_id)
    ]
    for callable_decl in callable_decls:
        context.callable_decl_by_id[callable_decl.callable_id] = callable_decl

    backend_program = ir_model.BackendProgram(
        schema_version=ir_model.BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=_entry_callable_id(program),
        data_blobs=tuple(context.data_blobs),
        interfaces=tuple(sorted(interfaces, key=lambda decl: interface_id_sort_key(decl.interface_id))),
        classes=tuple(sorted(classes, key=lambda decl: class_id_sort_key(decl.class_id))),
        callables=tuple(sorted(callable_decls, key=lambda decl: callable_id_sort_key(decl.callable_id))),
    )
    verify_backend_program(backend_program)
    return backend_program


def _entry_callable_id(program: LinkedSemanticProgram) -> FunctionId:
    for function in program.functions:
        if function.function_id.module_path == program.entry_module and function.function_id.name == "main":
            return function.function_id
    raise ValueError("Program entrypoint missing: expected 'fn main() -> i64'")


def _iter_interfaces(program: LinkedSemanticProgram) -> list[SemanticInterface]:
    interfaces: list[SemanticInterface] = []
    for module in program.ordered_modules:
        interfaces.extend(module.interfaces)
    return sorted(interfaces, key=lambda interface: interface_id_sort_key(interface.interface_id))


def _lower_interface_decl(interface: SemanticInterface) -> ir_model.BackendInterfaceDecl:
    return ir_model.BackendInterfaceDecl(
        interface_id=interface.interface_id,
        methods=tuple(sorted((method.method_id for method in interface.methods), key=interface_method_id_sort_key)),
    )


def _lower_class_decl(class_decl: SemanticClass) -> ir_model.BackendClassDecl:
    return ir_model.BackendClassDecl(
        class_id=class_decl.class_id,
        superclass_id=class_decl.superclass_id,
        implemented_interfaces=tuple(sorted(class_decl.implemented_interfaces, key=interface_id_sort_key)),
        fields=tuple(lower_field_decl(class_decl.class_id, field) for field in class_decl.fields),
        methods=tuple(sorted((method.method_id for method in class_decl.methods), key=callable_id_sort_key)),
        constructors=tuple(sorted((ctor.constructor_id for ctor in class_decl.constructors), key=callable_id_sort_key)),
    )


def _iter_lowered_callables(
    program: LinkedSemanticProgram,
    *,
    call_surface_by_id,
):
    for function in program.functions:
        yield lower_function_callable(function, call_surface_by_id=call_surface_by_id)
    for class_decl in program.classes:
        for method in class_decl.methods:
            yield lower_method_callable(class_decl.class_id, method, call_surface_by_id=call_surface_by_id)
        for constructor in class_decl.constructors:
            yield lower_constructor_callable(class_decl.class_id, constructor, call_surface_by_id=call_surface_by_id)


__all__ = ["ProgramLoweringContext", "lower_to_backend_ir"]