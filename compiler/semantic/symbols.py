from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from compiler.frontend.ast_nodes import ClassDecl, ConstructorDecl, FunctionDecl, InterfaceDecl, InterfaceMethodDecl, MethodDecl
from compiler.resolver import ModulePath, ProgramInfo


@dataclass(frozen=True)
class FunctionId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class ClassId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class MethodId:
    module_path: ModulePath
    class_name: str
    name: str


@dataclass(frozen=True)
class InterfaceId:
    module_path: ModulePath
    name: str


@dataclass(frozen=True)
class InterfaceMethodId:
    module_path: ModulePath
    interface_name: str
    name: str


@dataclass(frozen=True)
class ConstructorId:
    module_path: ModulePath
    class_name: str
    ordinal: int = 0


LocalOwnerId = FunctionId | MethodId | ConstructorId


@dataclass(frozen=True)
class LocalId:
    owner_id: LocalOwnerId
    ordinal: int

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("LocalId ordinal must be non-negative")


@dataclass(frozen=True)
class ProgramSymbolIndex:
    functions: dict[FunctionId, FunctionDecl]
    classes: dict[ClassId, ClassDecl]
    methods: dict[MethodId, MethodDecl]
    interfaces: dict[InterfaceId, InterfaceDecl]
    interface_methods: dict[InterfaceMethodId, InterfaceMethodDecl]
    constructors: dict[ConstructorId, ClassDecl | ConstructorDecl]
    local_functions_by_module: dict[ModulePath, dict[str, FunctionId]]
    local_classes_by_module: dict[ModulePath, dict[str, ClassId]]
    local_interfaces_by_module: dict[ModulePath, dict[str, InterfaceId]]
    class_ids_by_name: dict[str, set[ClassId]]
    interface_ids_by_name: dict[str, set[InterfaceId]]


def function_id_for_decl(module_path: ModulePath, decl: FunctionDecl) -> FunctionId:
    return FunctionId(module_path=module_path, name=decl.name)


def class_id_for_decl(module_path: ModulePath, decl: ClassDecl) -> ClassId:
    return ClassId(module_path=module_path, name=decl.name)


def method_id_for_decl(module_path: ModulePath, class_decl: ClassDecl, decl: MethodDecl) -> MethodId:
    return MethodId(module_path=module_path, class_name=class_decl.name, name=decl.name)


def interface_id_for_decl(module_path: ModulePath, decl: InterfaceDecl) -> InterfaceId:
    return InterfaceId(module_path=module_path, name=decl.name)


def interface_method_id_for_decl(
    module_path: ModulePath, interface_decl: InterfaceDecl, decl: InterfaceMethodDecl
) -> InterfaceMethodId:
    return InterfaceMethodId(module_path=module_path, interface_name=interface_decl.name, name=decl.name)


def constructor_id_for_class(module_path: ModulePath, decl: ClassDecl, *, ordinal: int = 0) -> ConstructorId:
    return ConstructorId(module_path=module_path, class_name=decl.name, ordinal=ordinal)


def iter_program_functions(program: ProgramInfo) -> Iterator[tuple[FunctionId, FunctionDecl]]:
    for module_path, module_info in program.modules.items():
        for function_decl in module_info.ast.functions:
            yield function_id_for_decl(module_path, function_decl), function_decl


def iter_program_classes(program: ProgramInfo) -> Iterator[tuple[ClassId, ClassDecl]]:
    for module_path, module_info in program.modules.items():
        for class_decl in module_info.ast.classes:
            yield class_id_for_decl(module_path, class_decl), class_decl


def iter_program_methods(program: ProgramInfo) -> Iterator[tuple[MethodId, MethodDecl]]:
    for module_path, module_info in program.modules.items():
        for class_decl in module_info.ast.classes:
            for method_decl in class_decl.methods:
                yield method_id_for_decl(module_path, class_decl, method_decl), method_decl


def iter_program_interfaces(program: ProgramInfo) -> Iterator[tuple[InterfaceId, InterfaceDecl]]:
    for module_path, module_info in program.modules.items():
        for interface_decl in module_info.ast.interfaces:
            yield interface_id_for_decl(module_path, interface_decl), interface_decl


def iter_program_interface_methods(program: ProgramInfo) -> Iterator[tuple[InterfaceMethodId, InterfaceMethodDecl]]:
    for module_path, module_info in program.modules.items():
        for interface_decl in module_info.ast.interfaces:
            for method_decl in interface_decl.methods:
                yield interface_method_id_for_decl(module_path, interface_decl, method_decl), method_decl


def iter_program_constructors(program: ProgramInfo) -> Iterator[tuple[ConstructorId, ClassDecl | ConstructorDecl]]:
    for module_path, module_info in program.modules.items():
        for class_decl in module_info.ast.classes:
            if not class_decl.constructors:
                yield constructor_id_for_class(module_path, class_decl), class_decl
                continue
            for ordinal, constructor_decl in enumerate(class_decl.constructors):
                yield constructor_id_for_class(module_path, class_decl, ordinal=ordinal), constructor_decl


def resolve_visible_interface_id(
    symbol_index: ProgramSymbolIndex, program: ProgramInfo, module_path: ModulePath, interface_name: str
) -> InterfaceId | None:
    local_interface = symbol_index.local_interfaces_by_module.get(module_path, {}).get(interface_name)
    if local_interface is not None:
        return local_interface

    module_info = program.modules.get(module_path)
    if module_info is None:
        return None

    matches: set[InterfaceId] = set()
    for import_info in module_info.imports.values():
        imported_module = program.modules[import_info.module_path]
        symbol = imported_module.exported_symbols.get(interface_name)
        if symbol is None or symbol.kind != "interface":
            continue

        interface_id = symbol_index.local_interfaces_by_module.get(symbol.owner_module_path, {}).get(interface_name)
        if interface_id is not None:
            matches.add(interface_id)

    if not matches:
        return None

    if len(matches) > 1:
        candidates = ", ".join(sorted(".".join(interface_id.module_path) for interface_id in matches))
        raise ValueError(f"Ambiguous imported interface '{interface_name}' (matches: {candidates})")

    return next(iter(matches))


def build_program_symbol_index(program: ProgramInfo) -> ProgramSymbolIndex:
    functions = dict(iter_program_functions(program))
    classes = dict(iter_program_classes(program))
    methods = dict(iter_program_methods(program))
    interfaces = dict(iter_program_interfaces(program))
    interface_methods = dict(iter_program_interface_methods(program))
    constructors = dict(iter_program_constructors(program))

    local_functions_by_module: dict[ModulePath, dict[str, FunctionId]] = {}
    local_classes_by_module: dict[ModulePath, dict[str, ClassId]] = {}
    local_interfaces_by_module: dict[ModulePath, dict[str, InterfaceId]] = {}
    class_ids_by_name: dict[str, set[ClassId]] = {}
    interface_ids_by_name: dict[str, set[InterfaceId]] = {}

    for module_path, module_info in program.modules.items():
        local_functions_by_module[module_path] = {
            function_decl.name: function_id_for_decl(module_path, function_decl)
            for function_decl in module_info.ast.functions
        }
        local_classes_by_module[module_path] = {
            class_decl.name: class_id_for_decl(module_path, class_decl) for class_decl in module_info.ast.classes
        }
        local_interfaces_by_module[module_path] = {
            interface_decl.name: interface_id_for_decl(module_path, interface_decl)
            for interface_decl in module_info.ast.interfaces
        }
        for class_decl in module_info.ast.classes:
            class_id = class_id_for_decl(module_path, class_decl)
            class_ids_by_name.setdefault(class_decl.name, set()).add(class_id)
        for interface_decl in module_info.ast.interfaces:
            interface_id = interface_id_for_decl(module_path, interface_decl)
            interface_ids_by_name.setdefault(interface_decl.name, set()).add(interface_id)

    return ProgramSymbolIndex(
        functions=functions,
        classes=classes,
        methods=methods,
        interfaces=interfaces,
        interface_methods=interface_methods,
        constructors=constructors,
        local_functions_by_module=local_functions_by_module,
        local_classes_by_module=local_classes_by_module,
        local_interfaces_by_module=local_interfaces_by_module,
        class_ids_by_name=class_ids_by_name,
        interface_ids_by_name=interface_ids_by_name,
    )
