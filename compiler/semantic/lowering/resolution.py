from __future__ import annotations

from dataclasses import dataclass

from compiler.frontend.ast_nodes import Expression, FieldAccessExpr, IdentifierExpr
from compiler.semantic.lowering.ids import (
    class_id_from_type_name,
    constructor_id_from_type_name,
    function_id_for_imported_name,
    function_id_for_local_name,
    function_id_for_module_member,
    interface_id_for_type_name,
    interface_method_id_for_type_name,
    resolve_instance_method_id,
    resolve_static_method_id,
)
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    MethodId,
    ProgramSymbolIndex,
)
from compiler.semantic.types import SemanticTypeRef
from compiler.typecheck.call_helpers import class_type_name_from_callable
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    lookup_interface_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner


@dataclass(frozen=True)
class ResolvedBoundMemberAccess:
    receiver: Expression
    receiver_type_ref: SemanticTypeRef


@dataclass(frozen=True)
class ResolvedFunctionValueTarget:
    function_id: FunctionId


@dataclass(frozen=True)
class ResolvedClassValueTarget:
    class_id: ClassId
    constructor_id: ConstructorId


@dataclass(frozen=True)
class ResolvedFieldMemberTarget:
    access: ResolvedBoundMemberAccess
    owner_class_id: ClassId
    field_name: str
    type_ref: SemanticTypeRef


@dataclass(frozen=True)
class ResolvedStaticMethodMemberTarget:
    method_id: MethodId


@dataclass(frozen=True)
class ResolvedInstanceMethodMemberTarget:
    method_id: MethodId
    access: ResolvedBoundMemberAccess


@dataclass(frozen=True)
class ResolvedInterfaceMethodMemberTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    access: ResolvedBoundMemberAccess


ResolvedValueTarget = ResolvedFunctionValueTarget | ResolvedClassValueTarget
ResolvedFieldAccessMemberTarget = (
    ResolvedFieldMemberTarget
    | ResolvedStaticMethodMemberTarget
    | ResolvedInstanceMethodMemberTarget
    | ResolvedInterfaceMethodMemberTarget
)


def resolve_identifier_value_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: IdentifierExpr
) -> ResolvedValueTarget | None:
    if expr.name in typecheck_ctx.functions:
        return ResolvedFunctionValueTarget(
            function_id=function_id_for_local_name(typecheck_ctx, symbol_index, expr.name)
        )

    if resolve_imported_function_sig(typecheck_ctx, expr.name, expr.span) is not None:
        return ResolvedFunctionValueTarget(
            function_id=function_id_for_imported_name(typecheck_ctx, symbol_index, expr.name)
        )

    imported_class_name = resolve_imported_class_name(typecheck_ctx, expr.name, expr.span)
    if expr.name in typecheck_ctx.classes or imported_class_name is not None:
        type_name = expr.name if imported_class_name is None else imported_class_name
        return ResolvedClassValueTarget(
            class_id=class_id_from_type_name(typecheck_ctx.module_path, type_name),
            constructor_id=constructor_id_from_type_name(typecheck_ctx.module_path, type_name),
        )

    return None


def resolve_module_member_value_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: FieldAccessExpr
) -> ResolvedValueTarget | None:
    module_member = resolve_module_member(typecheck_ctx, expr)
    if module_member is None:
        return None

    kind, owner_module, member_name = module_member
    if kind == "function":
        return ResolvedFunctionValueTarget(
            function_id=function_id_for_module_member(symbol_index, owner_module, member_name)
        )
    if kind == "class":
        return ResolvedClassValueTarget(
            class_id=ClassId(module_path=owner_module, name=member_name),
            constructor_id=ConstructorId(module_path=owner_module, class_name=member_name),
        )
    return None


def resolve_field_access_member_target(
    typecheck_ctx: TypeCheckContext, expr: FieldAccessExpr
) -> ResolvedFieldAccessMemberTarget | None:
    receiver_type = infer_expression_type(typecheck_ctx, expr.object_expr)
    static_owner_type_name = _callable_class_owner_type_name(receiver_type)
    if static_owner_type_name is not None:
        return ResolvedStaticMethodMemberTarget(
            method_id=resolve_static_method_id(typecheck_ctx, static_owner_type_name, expr.field_name)
        )

    if receiver_type.kind == "interface":
        interface_info = lookup_interface_by_type_name(typecheck_ctx, receiver_type.name)
        if interface_info is not None and expr.field_name in interface_info.methods:
            return ResolvedInterfaceMethodMemberTarget(
                interface_id=interface_id_for_type_name(typecheck_ctx.module_path, receiver_type.name),
                method_id=interface_method_id_for_type_name(
                    typecheck_ctx.module_path, receiver_type.name, expr.field_name
                ),
                access=_resolve_bound_member_access(typecheck_ctx, expr.object_expr, receiver_type),
            )

    class_info = lookup_class_by_type_name(typecheck_ctx, receiver_type.name)
    if class_info is None:
        return None

    if expr.field_name in class_info.fields:
        field_member = class_info.field_members[expr.field_name]
        field_type = qualify_member_type_for_owner(typecheck_ctx, class_info.fields[expr.field_name], field_member.owner_class_name)
        return ResolvedFieldMemberTarget(
            access=_resolve_bound_member_access(typecheck_ctx, expr.object_expr, receiver_type),
            owner_class_id=class_id_from_type_name(typecheck_ctx.module_path, field_member.owner_class_name),
            field_name=expr.field_name,
            type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, field_type),
        )

    if expr.field_name in class_info.methods:
        method_id = resolve_instance_method_id(typecheck_ctx, receiver_type, expr.field_name)
        if method_id is None:
            return None
        return ResolvedInstanceMethodMemberTarget(
            method_id=method_id, access=_resolve_bound_member_access(typecheck_ctx, expr.object_expr, receiver_type)
        )

    return None


def _resolve_bound_member_access(
    typecheck_ctx: TypeCheckContext, receiver: Expression, receiver_type: TypeInfo | None = None
) -> ResolvedBoundMemberAccess:
    effective_receiver_type = (
        receiver_type if receiver_type is not None else infer_expression_type(typecheck_ctx, receiver)
    )
    return ResolvedBoundMemberAccess(
        receiver=receiver, receiver_type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, effective_receiver_type)
    )


def _callable_class_owner_type_name(receiver_type: TypeInfo) -> str | None:
    if receiver_type.kind != "callable" or not receiver_type.name.startswith("__class__:"):
        return None
    return class_type_name_from_callable(receiver_type.name)
