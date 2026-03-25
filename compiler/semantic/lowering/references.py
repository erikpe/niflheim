from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from compiler.common.collection_protocols import CollectionOpKind
from compiler.frontend.ast_nodes import Expression, FieldAccessExpr, IdentifierExpr, IndexExpr
from compiler.semantic.ir import *
from compiler.semantic.lowering.locals import LocalIdTracker
from compiler.semantic.symbols import ClassId, LocalId, ProgramSymbolIndex
from compiler.typecheck.call_helpers import class_type_name_from_callable
from compiler.typecheck.context import TypeCheckContext, lookup_variable
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.structural import ensure_structural_set_method_available_for_index_assignment
from compiler.typecheck.type_resolution import qualify_member_type_for_owner

from compiler.semantic.lowering.collections import resolve_collection_dispatch
from compiler.semantic.lowering.ids import *


LowerExpr = Callable[[Expression], SemanticExpr]


@dataclass(frozen=True)
class ResolvedLocalRefTarget:
    local_id: LocalId
    name: str
    type_name: str


@dataclass(frozen=True)
class ResolvedFunctionRefTarget:
    function_id: object


@dataclass(frozen=True)
class ResolvedClassRefTarget:
    class_id: ClassId


@dataclass(frozen=True)
class ResolvedMethodRefTarget:
    method_id: object
    receiver: Expression | None


@dataclass(frozen=True)
class ResolvedFieldReadTarget:
    receiver: Expression
    receiver_type_name: str
    owner_class_id: ClassId
    field_name: str
    type_name: str


@dataclass(frozen=True)
class ResolvedLocalLValueTarget:
    local_id: LocalId
    name: str
    type_name: str


@dataclass(frozen=True)
class ResolvedFieldLValueTarget:
    receiver: Expression
    receiver_type_name: str
    owner_class_id: ClassId
    field_name: str
    type_name: str


@dataclass(frozen=True)
class ResolvedIndexLValueTarget:
    target: Expression
    index: Expression
    value_type_name: str


ResolvedRefTarget = (
    ResolvedLocalRefTarget
    | ResolvedFunctionRefTarget
    | ResolvedClassRefTarget
    | ResolvedMethodRefTarget
    | ResolvedFieldReadTarget
)


ResolvedLValueTarget = ResolvedLocalLValueTarget | ResolvedFieldLValueTarget | ResolvedIndexLValueTarget


def resolve_identifier_ref_target(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: IdentifierExpr,
    local_id_tracker: LocalIdTracker | None,
) -> ResolvedRefTarget:
    local_type = lookup_variable(typecheck_ctx, expr.name)
    if local_type is not None:
        return ResolvedLocalRefTarget(
            local_id=_require_local_id(local_id_tracker, expr.name),
            name=expr.name,
            type_name=local_type.name,
        )

    if expr.name in typecheck_ctx.functions:
        return ResolvedFunctionRefTarget(function_id=function_id_for_local_name(typecheck_ctx, symbol_index, expr.name))

    if resolve_imported_function_sig(typecheck_ctx, expr.name, expr.span) is not None:
        return ResolvedFunctionRefTarget(
            function_id=function_id_for_imported_name(typecheck_ctx, symbol_index, expr.name)
        )

    imported_class_name = resolve_imported_class_name(typecheck_ctx, expr.name, expr.span)
    if expr.name in typecheck_ctx.classes or imported_class_name is not None:
        type_name = expr.name if imported_class_name is None else imported_class_name
        return ResolvedClassRefTarget(class_id=class_id_from_type_name(typecheck_ctx.module_path, type_name))

    raise TypeError(f"Unsupported identifier expression for semantic lowering: {expr.name}")


def resolve_field_access_ref_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: FieldAccessExpr
) -> ResolvedRefTarget:
    module_member = resolve_module_member(typecheck_ctx, expr)
    if module_member is not None:
        kind, owner_module, member_name = module_member
        if kind == "function":
            return ResolvedFunctionRefTarget(
                function_id=function_id_for_module_member(symbol_index, owner_module, member_name)
            )
        if kind == "class":
            return ResolvedClassRefTarget(class_id=class_id_for_module_member(owner_module, member_name))
        raise TypeError("Module references are not first-class semantic expressions")

    receiver_type = infer_expression_type(typecheck_ctx, expr.object_expr)
    if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
        return ResolvedMethodRefTarget(
            method_id=method_id_for_type_name(
                typecheck_ctx.module_path, class_type_name_from_callable(receiver_type.name), expr.field_name
            ),
            receiver=None,
        )

    class_info = lookup_class_by_type_name(typecheck_ctx, receiver_type.name)
    if class_info is None:
        raise TypeError(f"Unsupported field access for semantic lowering: {expr.field_name}")

    if expr.field_name in class_info.fields:
        field_type = qualify_member_type_for_owner(
            typecheck_ctx, class_info.fields[expr.field_name], receiver_type.name
        )
        return ResolvedFieldReadTarget(
            receiver=expr.object_expr,
            receiver_type_name=receiver_type.name,
            owner_class_id=class_id_from_type_name(typecheck_ctx.module_path, receiver_type.name),
            field_name=expr.field_name,
            type_name=field_type.name,
        )

    if expr.field_name in class_info.methods:
        return ResolvedMethodRefTarget(
            method_id=method_id_for_type_name(typecheck_ctx.module_path, receiver_type.name, expr.field_name),
            receiver=expr.object_expr,
        )

    raise TypeError(f"Unsupported field access for semantic lowering: {expr.field_name}")


def lower_resolved_ref(
    resolved_target: ResolvedRefTarget, type_name: str, span, *, lower_expr: LowerExpr
) -> SemanticExpr:
    if isinstance(resolved_target, ResolvedLocalRefTarget):
        return LocalRefExpr(
            local_id=resolved_target.local_id,
            name=resolved_target.name,
            type_name=resolved_target.type_name,
            span=span,
        )

    if isinstance(resolved_target, ResolvedFunctionRefTarget):
        return FunctionRefExpr(function_id=resolved_target.function_id, type_name=type_name, span=span)

    if isinstance(resolved_target, ResolvedClassRefTarget):
        return ClassRefExpr(class_id=resolved_target.class_id, type_name=type_name, span=span)

    if isinstance(resolved_target, ResolvedMethodRefTarget):
        receiver = None if resolved_target.receiver is None else lower_expr(resolved_target.receiver)
        return MethodRefExpr(method_id=resolved_target.method_id, receiver=receiver, type_name=type_name, span=span)

    return FieldReadExpr(
        receiver=lower_expr(resolved_target.receiver),
        receiver_type_name=resolved_target.receiver_type_name,
        owner_class_id=resolved_target.owner_class_id,
        field_name=resolved_target.field_name,
        type_name=resolved_target.type_name,
        span=span,
    )


def lower_lvalue(
    typecheck_ctx: TypeCheckContext,
    expr: Expression,
    *,
    lower_expr: LowerExpr,
    local_id_tracker: LocalIdTracker | None,
):
    resolved_target = resolve_lvalue_target(typecheck_ctx, expr, local_id_tracker)

    if isinstance(resolved_target, ResolvedLocalLValueTarget):
        return LocalLValue(
            local_id=resolved_target.local_id,
            name=resolved_target.name,
            type_name=resolved_target.type_name,
            span=expr.span,
        )

    if isinstance(resolved_target, ResolvedFieldLValueTarget):
        return FieldLValue(
            receiver=lower_expr(resolved_target.receiver),
            receiver_type_name=resolved_target.receiver_type_name,
            owner_class_id=resolved_target.owner_class_id,
            field_name=resolved_target.field_name,
            type_name=resolved_target.type_name,
            span=expr.span,
        )

    return IndexLValue(
        target=lower_expr(resolved_target.target),
        index=lower_expr(resolved_target.index),
        value_type_name=resolved_target.value_type_name,
        dispatch=resolve_collection_dispatch(
            typecheck_ctx,
            infer_expression_type(typecheck_ctx, resolved_target.target),
            operation=CollectionOpKind.INDEX_SET,
        ),
        span=expr.span,
    )


def resolve_lvalue_target(
    typecheck_ctx: TypeCheckContext, expr: Expression, local_id_tracker: LocalIdTracker | None
) -> ResolvedLValueTarget:
    if isinstance(expr, IdentifierExpr):
        local_type = lookup_variable(typecheck_ctx, expr.name)
        if local_type is None:
            raise ValueError(f"Unknown local assignment target '{expr.name}'")
        return ResolvedLocalLValueTarget(
            local_id=_require_local_id(local_id_tracker, expr.name),
            name=expr.name,
            type_name=local_type.name,
        )

    if isinstance(expr, FieldAccessExpr):
        receiver_type_name = infer_expression_type(typecheck_ctx, expr.object_expr).name
        return ResolvedFieldLValueTarget(
            receiver=expr.object_expr,
            receiver_type_name=receiver_type_name,
            owner_class_id=class_id_from_type_name(typecheck_ctx.module_path, receiver_type_name),
            field_name=expr.field_name,
            type_name=infer_expression_type(typecheck_ctx, expr).name,
        )

    if isinstance(expr, IndexExpr):
        return ResolvedIndexLValueTarget(
            target=expr.object_expr,
            index=expr.index_expr,
            value_type_name=resolve_index_assignment_value_type_name(typecheck_ctx, expr),
        )

    raise TypeError(f"Unsupported lvalue for semantic lowering: {type(expr).__name__}")


def resolve_index_assignment_value_type_name(typecheck_ctx: TypeCheckContext, expr: IndexExpr) -> str:
    object_type = infer_expression_type(typecheck_ctx, expr.object_expr)
    if object_type.element_type is not None:
        return object_type.element_type.name

    method_sig = ensure_structural_set_method_available_for_index_assignment(typecheck_ctx, object_type, expr.span)
    return qualify_member_type_for_owner(typecheck_ctx, method_sig.params[1], object_type.name).name


def _require_local_id(local_id_tracker: LocalIdTracker | None, name: str) -> LocalId:
    if local_id_tracker is None:
        raise ValueError(f"Semantic lowering requires a LocalIdTracker for local '{name}'")

    local_id = local_id_tracker.lookup_local(name)
    if local_id is None:
        raise ValueError(f"Semantic lowering missing LocalId for local '{name}'")
    return local_id
