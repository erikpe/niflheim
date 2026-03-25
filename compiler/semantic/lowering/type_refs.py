from __future__ import annotations

from dataclasses import replace

from compiler.semantic.types import SemanticTypeRef, semantic_type_ref_from_type_info
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import TypeInfo


def semantic_type_ref_from_checked_type(typecheck_ctx: TypeCheckContext, type_info: TypeInfo) -> SemanticTypeRef:
    canonical_ref = semantic_type_ref_from_type_info(typecheck_ctx.module_path, _canonicalize_checked_type(typecheck_ctx, type_info))
    display_ref = semantic_type_ref_from_type_info(typecheck_ctx.module_path, type_info)
    return _merge_display_names(canonical_ref, display_ref)


def _canonicalize_checked_type(typecheck_ctx: TypeCheckContext, type_info: TypeInfo) -> TypeInfo:
    if type_info.element_type is not None:
        element_type = _canonicalize_checked_type(typecheck_ctx, type_info.element_type)
        if element_type == type_info.element_type:
            return type_info
        return TypeInfo(name=f"{element_type.name}[]", kind=type_info.kind, element_type=element_type)

    if type_info.kind == "callable":
        param_types = None
        if type_info.callable_params is not None:
            param_types = [_canonicalize_checked_type(typecheck_ctx, param_type) for param_type in type_info.callable_params]
        return_type = None
        if type_info.callable_return is not None:
            return_type = _canonicalize_checked_type(typecheck_ctx, type_info.callable_return)
        if param_types == type_info.callable_params and return_type == type_info.callable_return:
            return type_info
        return TypeInfo(
            name=type_info.name,
            kind=type_info.kind,
            callable_params=param_types,
            callable_return=return_type,
        )

    qualified_name = _qualified_nominal_name(typecheck_ctx, type_info)
    if qualified_name is None or qualified_name == type_info.name:
        return type_info
    return TypeInfo(name=qualified_name, kind=type_info.kind)


def _qualified_nominal_name(typecheck_ctx: TypeCheckContext, type_info: TypeInfo) -> str | None:
    if type_info.kind == "reference" and "::" not in type_info.name and type_info.name in typecheck_ctx.classes:
        return f"{'.'.join(typecheck_ctx.module_path)}::{type_info.name}"

    if type_info.kind == "interface" and "::" not in type_info.name and type_info.name in typecheck_ctx.interfaces:
        return f"{'.'.join(typecheck_ctx.module_path)}::{type_info.name}"

    return None


def _merge_display_names(canonical_ref: SemanticTypeRef, display_ref: SemanticTypeRef) -> SemanticTypeRef:
    if canonical_ref.kind != display_ref.kind:
        return canonical_ref

    element_type = canonical_ref.element_type
    if canonical_ref.element_type is not None and display_ref.element_type is not None:
        element_type = _merge_display_names(canonical_ref.element_type, display_ref.element_type)

    param_types = canonical_ref.param_types
    if canonical_ref.param_types and display_ref.param_types and len(canonical_ref.param_types) == len(display_ref.param_types):
        param_types = tuple(
            _merge_display_names(canonical_param, display_param)
            for canonical_param, display_param in zip(canonical_ref.param_types, display_ref.param_types)
        )

    return_type = canonical_ref.return_type
    if canonical_ref.return_type is not None and display_ref.return_type is not None:
        return_type = _merge_display_names(canonical_ref.return_type, display_ref.return_type)

    return replace(
        canonical_ref,
        display_name=display_ref.display_name,
        element_type=element_type,
        param_types=param_types,
        return_type=return_type,
    )