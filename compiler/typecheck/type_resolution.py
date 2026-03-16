from __future__ import annotations

from compiler.ast_nodes import ArrayTypeRef, FunctionTypeRef, TypeRefNode
from compiler.codegen.strings import STR_CLASS_NAME
from compiler.lexer import SourceSpan
from compiler.resolver import ModuleInfo, ModulePath
from compiler.typecheck.model import (
    ClassInfo,
    PRIMITIVE_TYPE_NAMES,
    REFERENCE_BUILTIN_TYPE_NAMES,
    TypeCheckError,
    TypeInfo,
)
from compiler.typecheck.module_lookup import (
    resolve_imported_class_name,
    resolve_qualified_imported_class_name,
    resolve_unique_global_class_name,
)
from compiler.typecheck.relations import format_function_type_name


def resolve_type_ref(
    type_ref: TypeRefNode,
    *,
    local_classes: dict[str, ClassInfo],
    module_path: ModulePath | None,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> TypeInfo:
    if isinstance(type_ref, ArrayTypeRef):
        element_type = resolve_type_ref(
            type_ref.element_type,
            local_classes=local_classes,
            module_path=module_path,
            modules=modules,
            module_class_infos=module_class_infos,
        )
        return TypeInfo(name=f"{element_type.name}[]", kind="reference", element_type=element_type)

    if isinstance(type_ref, FunctionTypeRef):
        param_types = [
            resolve_type_ref(
                param_type,
                local_classes=local_classes,
                module_path=module_path,
                modules=modules,
                module_class_infos=module_class_infos,
            )
            for param_type in type_ref.param_types
        ]
        return_type = resolve_type_ref(
            type_ref.return_type,
            local_classes=local_classes,
            module_path=module_path,
            modules=modules,
            module_class_infos=module_class_infos,
        )
        return TypeInfo(
            name=format_function_type_name(param_types, return_type),
            kind="callable",
            callable_params=param_types,
            callable_return=return_type,
        )

    name = type_ref.name
    if name in PRIMITIVE_TYPE_NAMES:
        return TypeInfo(name=name, kind="primitive")

    if "." in name:
        qualified_name = resolve_qualified_imported_class_name(
            name,
            type_ref.span,
            modules=modules,
            module_path=module_path,
        )
        if qualified_name is not None:
            return TypeInfo(name=qualified_name, kind="reference")

    if name in local_classes:
        return TypeInfo(name=name, kind="reference")

    imported_name = resolve_imported_class_name(
        name,
        type_ref.span,
        modules=modules,
        module_path=module_path,
    )
    if imported_name is not None:
        return TypeInfo(name=imported_name, kind="reference")

    if name in REFERENCE_BUILTIN_TYPE_NAMES:
        return TypeInfo(name=name, kind="reference")

    raise TypeCheckError(f"Unknown type '{name}'", type_ref.span)


def resolve_string_type(
    span: SourceSpan,
    *,
    local_classes: dict[str, ClassInfo],
    module_path: ModulePath | None,
    modules: dict[ModulePath, ModuleInfo] | None,
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> TypeInfo:
    if STR_CLASS_NAME in local_classes:
        return TypeInfo(name=STR_CLASS_NAME, kind="reference")

    imported_name = resolve_imported_class_name(
        STR_CLASS_NAME,
        span,
        modules=modules,
        module_path=module_path,
    )
    if imported_name is not None:
        return TypeInfo(name=imported_name, kind="reference")

    global_name = resolve_unique_global_class_name(
        STR_CLASS_NAME,
        span,
        module_class_infos=module_class_infos,
    )
    if global_name is not None:
        return TypeInfo(name=global_name, kind="reference")

    raise TypeCheckError(f"Unknown type '{STR_CLASS_NAME}'", span)


def qualify_member_type_for_owner(
    member_type: TypeInfo,
    owner_type_name: str,
    *,
    module_class_infos: dict[ModulePath, dict[str, ClassInfo]] | None,
) -> TypeInfo:
    if member_type.element_type is not None:
        qualified_element_type = qualify_member_type_for_owner(
            member_type.element_type,
            owner_type_name,
            module_class_infos=module_class_infos,
        )
        if qualified_element_type == member_type.element_type:
            return member_type
        return TypeInfo(name=f"{qualified_element_type.name}[]", kind="reference", element_type=qualified_element_type)

    if member_type.kind != "reference" or "::" in member_type.name:
        return member_type
    if "::" not in owner_type_name or module_class_infos is None:
        return member_type

    owner_dotted, _owner_class_name = owner_type_name.split("::", 1)
    owner_module = tuple(owner_dotted.split("."))
    owner_classes = module_class_infos.get(owner_module)
    if owner_classes is None or member_type.name not in owner_classes:
        return member_type

    return TypeInfo(name=f"{owner_dotted}::{member_type.name}", kind="reference")
