from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from compiler.ast_nodes import ClassDecl, FunctionDecl, MethodDecl
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
class ConstructorId:
    module_path: ModulePath
    class_name: str


@dataclass(frozen=True)
class SyntheticId:
    kind: str
    owner: str
    name: str


@dataclass(frozen=True)
class ProgramSymbolIndex:
    functions: dict[FunctionId, FunctionDecl]
    classes: dict[ClassId, ClassDecl]
    methods: dict[MethodId, MethodDecl]
    constructors: dict[ConstructorId, ClassDecl]
    local_functions_by_module: dict[ModulePath, dict[str, FunctionId]]
    local_classes_by_module: dict[ModulePath, dict[str, ClassId]]
    class_ids_by_name: dict[str, set[ClassId]]


def function_id_for_decl(module_path: ModulePath, decl: FunctionDecl) -> FunctionId:
    return FunctionId(module_path=module_path, name=decl.name)


def class_id_for_decl(module_path: ModulePath, decl: ClassDecl) -> ClassId:
    return ClassId(module_path=module_path, name=decl.name)


def method_id_for_decl(module_path: ModulePath, class_decl: ClassDecl, decl: MethodDecl) -> MethodId:
    return MethodId(module_path=module_path, class_name=class_decl.name, name=decl.name)


def constructor_id_for_class(module_path: ModulePath, decl: ClassDecl) -> ConstructorId:
    return ConstructorId(module_path=module_path, class_name=decl.name)


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


def iter_program_constructors(program: ProgramInfo) -> Iterator[tuple[ConstructorId, ClassDecl]]:
    for module_path, module_info in program.modules.items():
        for class_decl in module_info.ast.classes:
            yield constructor_id_for_class(module_path, class_decl), class_decl


def build_program_symbol_index(program: ProgramInfo) -> ProgramSymbolIndex:
    functions = dict(iter_program_functions(program))
    classes = dict(iter_program_classes(program))
    methods = dict(iter_program_methods(program))
    constructors = dict(iter_program_constructors(program))

    local_functions_by_module: dict[ModulePath, dict[str, FunctionId]] = {}
    local_classes_by_module: dict[ModulePath, dict[str, ClassId]] = {}
    class_ids_by_name: dict[str, set[ClassId]] = {}

    for module_path, module_info in program.modules.items():
        local_functions_by_module[module_path] = {
            function_decl.name: function_id_for_decl(module_path, function_decl)
            for function_decl in module_info.ast.functions
        }
        local_classes_by_module[module_path] = {
            class_decl.name: class_id_for_decl(module_path, class_decl) for class_decl in module_info.ast.classes
        }
        for class_decl in module_info.ast.classes:
            class_id = class_id_for_decl(module_path, class_decl)
            class_ids_by_name.setdefault(class_decl.name, set()).add(class_id)

    return ProgramSymbolIndex(
        functions=functions,
        classes=classes,
        methods=methods,
        constructors=constructors,
        local_functions_by_module=local_functions_by_module,
        local_classes_by_module=local_classes_by_module,
        class_ids_by_name=class_ids_by_name,
    )
