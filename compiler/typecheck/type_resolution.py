from __future__ import annotations

from compiler.common.type_names import PRIMITIVE_TYPE_NAMES, REFERENCE_BUILTIN_TYPE_NAMES, TYPE_NAME_STR
from compiler.frontend.ast_nodes import ArrayTypeRef, FunctionTypeRef, TypeRefNode
from compiler.typecheck.context import TypeCheckContext
from compiler.frontend.lexer import SourceSpan
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import (
    resolve_imported_class_name,
    resolve_imported_interface_name,
    resolve_qualified_imported_class_name,
    resolve_qualified_imported_interface_name,
    resolve_unique_global_class_name,
)
from compiler.typecheck.relations import format_function_type_name


def resolve_type_ref(ctx: TypeCheckContext, type_ref: TypeRefNode) -> TypeInfo:
    if isinstance(type_ref, ArrayTypeRef):
        element_type = resolve_type_ref(ctx, type_ref.element_type)
        return TypeInfo(name=f"{element_type.name}[]", kind="reference", element_type=element_type)

    if isinstance(type_ref, FunctionTypeRef):
        param_types = [resolve_type_ref(ctx, param_type) for param_type in type_ref.param_types]
        return_type = resolve_type_ref(ctx, type_ref.return_type)
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
        qualified_interface_name = resolve_qualified_imported_interface_name(ctx, name, type_ref.span, allow_missing=True)
        if qualified_interface_name is not None:
            return TypeInfo(name=qualified_interface_name, kind="interface")

        qualified_name = resolve_qualified_imported_class_name(ctx, name, type_ref.span)
        if qualified_name is not None:
            return TypeInfo(name=qualified_name, kind="reference")

    if name in ctx.interfaces:
        return TypeInfo(name=name, kind="interface")

    if name in ctx.classes:
        return TypeInfo(name=name, kind="reference")

    imported_interface_name = resolve_imported_interface_name(ctx, name, type_ref.span)
    imported_class_name = resolve_imported_class_name(ctx, name, type_ref.span)

    if imported_interface_name is not None and imported_class_name is not None:
        raise TypeCheckError(f"Ambiguous imported type '{name}'", type_ref.span)

    if imported_interface_name is not None:
        return TypeInfo(name=imported_interface_name, kind="interface")

    if imported_class_name is not None:
        return TypeInfo(name=imported_class_name, kind="reference")

    if name in REFERENCE_BUILTIN_TYPE_NAMES:
        return TypeInfo(name=name, kind="reference")

    raise TypeCheckError(f"Unknown type '{name}'", type_ref.span)


def resolve_string_type(ctx: TypeCheckContext, span: SourceSpan) -> TypeInfo:
    if TYPE_NAME_STR in ctx.classes:
        return TypeInfo(name=TYPE_NAME_STR, kind="reference")

    imported_name = resolve_imported_class_name(ctx, TYPE_NAME_STR, span)
    if imported_name is not None:
        return TypeInfo(name=imported_name, kind="reference")

    global_name = resolve_unique_global_class_name(ctx, TYPE_NAME_STR, span)
    if global_name is not None:
        return TypeInfo(name=global_name, kind="reference")

    raise TypeCheckError(f"Unknown type '{TYPE_NAME_STR}'", span)


def qualify_member_type_for_owner(ctx: TypeCheckContext, member_type: TypeInfo, owner_type_name: str) -> TypeInfo:
    if member_type.element_type is not None:
        qualified_element_type = qualify_member_type_for_owner(ctx, member_type.element_type, owner_type_name)
        if qualified_element_type == member_type.element_type:
            return member_type
        return TypeInfo(name=f"{qualified_element_type.name}[]", kind="reference", element_type=qualified_element_type)

    if member_type.kind not in {"reference", "interface"} or "::" in member_type.name:
        return member_type
    if "::" not in owner_type_name or ctx.module_class_infos is None:
        return member_type

    owner_dotted, _owner_class_name = owner_type_name.split("::", 1)
    owner_module = tuple(owner_dotted.split("."))
    owner_classes = ctx.module_class_infos.get(owner_module)
    if owner_classes is not None and member_type.name in owner_classes:
        return TypeInfo(name=f"{owner_dotted}::{member_type.name}", kind=member_type.kind)

    owner_interfaces = None if ctx.module_interface_infos is None else ctx.module_interface_infos.get(owner_module)
    if owner_interfaces is not None and member_type.name in owner_interfaces:
        return TypeInfo(name=f"{owner_dotted}::{member_type.name}", kind=member_type.kind)

    return member_type
