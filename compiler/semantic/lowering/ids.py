from __future__ import annotations

from compiler.resolver import ModulePath
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.symbols import *
from compiler.semantic.types import semantic_type_canonical_name, semantic_type_is_array
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name


def resolve_instance_method_id(
    typecheck_ctx: TypeCheckContext, receiver_type: TypeInfo, method_name: str
) -> MethodId | None:
    receiver_type_ref = semantic_type_ref_from_checked_type(typecheck_ctx, receiver_type)
    receiver_type_name = semantic_type_canonical_name(receiver_type_ref)
    if semantic_type_is_array(receiver_type_ref):
        return None

    class_info = lookup_class_by_type_name(typecheck_ctx, receiver_type_name)
    if class_info is None:
        raise ValueError(f"Cannot resolve structural method '{method_name}' on non-class type '{receiver_type_name}'")

    method_member = class_info.method_members.get(method_name)
    if method_member is None:
        raise ValueError(f"Missing instance method '{method_name}' on type '{receiver_type_name}'")
    method_sig = method_member.signature
    if method_sig.is_static:
        raise ValueError(f"Expected instance method '{method_name}' on type '{receiver_type_name}'")
    return method_id_for_type_name(typecheck_ctx.module_path, method_member.owner_class_name, method_name)


def resolve_static_method_id(typecheck_ctx: TypeCheckContext, owner_type_name: str, method_name: str) -> MethodId:
    class_info = lookup_class_by_type_name(typecheck_ctx, owner_type_name)
    if class_info is None:
        raise ValueError(f"Cannot resolve static method '{method_name}' on non-class type '{owner_type_name}'")

    method_member = class_info.method_members.get(method_name)
    if method_member is None:
        raise ValueError(f"Missing static method '{method_name}' on type '{owner_type_name}'")
    method_sig = method_member.signature
    if not method_sig.is_static:
        raise ValueError(f"Expected static method '{method_name}' on type '{owner_type_name}'")
    return method_id_for_type_name(typecheck_ctx.module_path, method_member.owner_class_name, method_name)


def function_id_for_local_name(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, name: str
) -> FunctionId:
    module_path = typecheck_ctx.module_path
    assert module_path is not None
    return symbol_index.local_functions_by_module[module_path][name]


def function_id_for_imported_name(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, name: str
) -> FunctionId:
    module_path = typecheck_ctx.module_path
    modules = typecheck_ctx.modules
    assert module_path is not None
    assert modules is not None

    current_module = modules[module_path]
    matches: set[FunctionId] = set()
    for import_info in current_module.imports.values():
        function_id = symbol_index.local_functions_by_module.get(import_info.module_path, {}).get(name)
        if function_id is not None:
            matches.add(function_id)
    if len(matches) != 1:
        raise ValueError(f"Expected unique imported function '{name}'")
    return next(iter(matches))


def function_id_for_module_member(symbol_index: ProgramSymbolIndex, owner_module: ModulePath, name: str) -> FunctionId:
    return symbol_index.local_functions_by_module[owner_module][name]


def class_id_for_module_member(owner_module: ModulePath, name: str) -> ClassId:
    return ClassId(module_path=owner_module, name=name)


def constructor_id_for_module_member(owner_module: ModulePath, name: str) -> ConstructorId:
    return constructor_id_from_type_name(owner_module, name)


def class_id_from_type_name(current_module_path: ModulePath | None, type_name: str) -> ClassId:
    owner_module, class_name = split_type_name(current_module_path, type_name)
    return class_id_for_module_member(owner_module, class_name)


def constructor_id_from_type_name(current_module_path: ModulePath | None, type_name: str) -> ConstructorId:
    owner_module, class_name = split_type_name(current_module_path, type_name)
    return ConstructorId(module_path=owner_module, class_name=class_name)


def method_id_for_type_name(current_module_path: ModulePath | None, type_name: str, method_name: str) -> MethodId:
    owner_module, class_name = split_type_name(current_module_path, type_name)
    return MethodId(module_path=owner_module, class_name=class_name, name=method_name)


def interface_id_for_type_name(current_module_path: ModulePath | None, type_name: str) -> InterfaceId:
    owner_module, interface_name = split_type_name(current_module_path, type_name)
    return InterfaceId(module_path=owner_module, name=interface_name)


def interface_method_id_for_type_name(
    current_module_path: ModulePath | None, type_name: str, method_name: str
) -> InterfaceMethodId:
    owner_module, interface_name = split_type_name(current_module_path, type_name)
    return InterfaceMethodId(module_path=owner_module, interface_name=interface_name, name=method_name)


def split_type_name(current_module_path: ModulePath | None, type_name: str) -> tuple[ModulePath, str]:
    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return tuple(owner_dotted.split(".")), class_name
    if current_module_path is None:
        raise ValueError(f"Cannot resolve unqualified type name '{type_name}' without a module path")
    return current_module_path, type_name
