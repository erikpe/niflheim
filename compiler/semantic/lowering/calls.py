from __future__ import annotations

from dataclasses import dataclass

from compiler.frontend.ast_nodes import CallExpr, Expression, FieldAccessExpr, IdentifierExpr
from compiler.semantic.symbols import (
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    MethodId,
    ProgramSymbolIndex,
)
from compiler.typecheck.call_helpers import select_constructor_overload
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.calls import infer_call_type
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.semantic.lowering.resolution import (
    ResolvedBoundMemberAccess,
    ResolvedClassValueTarget,
    ResolvedFunctionValueTarget,
    ResolvedInstanceMethodMemberTarget,
    ResolvedInterfaceMethodMemberTarget,
    ResolvedStaticMethodMemberTarget,
    resolve_field_access_member_target,
    resolve_identifier_value_target,
    resolve_module_member_value_target,
)


@dataclass(frozen=True)
class ResolvedFunctionCallTarget:
    function_id: FunctionId


@dataclass(frozen=True)
class ResolvedConstructorCallTarget:
    constructor_id: ConstructorId


@dataclass(frozen=True)
class ResolvedStaticMethodCallTarget:
    method_id: MethodId


@dataclass(frozen=True)
class ResolvedInstanceMethodCallTarget:
    method_id: MethodId
    access: ResolvedBoundMemberAccess


@dataclass(frozen=True)
class ResolvedInterfaceMethodCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    access: ResolvedBoundMemberAccess


@dataclass(frozen=True)
class ResolvedCallableValueCallTarget:
    callee: Expression


ResolvedCallTarget = (
    ResolvedFunctionCallTarget
    | ResolvedConstructorCallTarget
    | ResolvedStaticMethodCallTarget
    | ResolvedInstanceMethodCallTarget
    | ResolvedInterfaceMethodCallTarget
    | ResolvedCallableValueCallTarget
)


def resolve_call_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: CallExpr
) -> ResolvedCallTarget:
    identifier_target = resolve_identifier_call_target(typecheck_ctx, symbol_index, expr)
    if identifier_target is not None:
        return identifier_target

    field_access_target = resolve_field_access_call_target(typecheck_ctx, symbol_index, expr)
    if field_access_target is not None:
        return field_access_target

    infer_call_type(typecheck_ctx, expr)
    return ResolvedCallableValueCallTarget(callee=expr.callee)


def resolve_identifier_call_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: CallExpr
) -> ResolvedCallTarget | None:
    if not isinstance(expr.callee, IdentifierExpr):
        return None

    value_target = resolve_identifier_value_target(typecheck_ctx, symbol_index, expr.callee)
    if isinstance(value_target, ResolvedFunctionValueTarget):
        return ResolvedFunctionCallTarget(function_id=value_target.function_id)
    if isinstance(value_target, ResolvedClassValueTarget):
        return ResolvedConstructorCallTarget(
            constructor_id=_resolve_selected_constructor_id(
                typecheck_ctx,
                _class_type_name_for_module_member(value_target.class_id),
                expr,
            )
        )

    return None


def resolve_field_access_call_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: CallExpr
) -> ResolvedCallTarget | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    module_member_target = resolve_module_member_value_target(typecheck_ctx, symbol_index, expr.callee)
    if isinstance(module_member_target, ResolvedFunctionValueTarget):
        return ResolvedFunctionCallTarget(function_id=module_member_target.function_id)
    if isinstance(module_member_target, ResolvedClassValueTarget):
        class_type_name = _class_type_name_for_module_member(module_member_target.class_id)
        return ResolvedConstructorCallTarget(
            constructor_id=_resolve_selected_constructor_id(typecheck_ctx, class_type_name, expr)
        )

    member_target = resolve_field_access_member_target(typecheck_ctx, expr.callee)
    if isinstance(member_target, ResolvedStaticMethodMemberTarget):
        return ResolvedStaticMethodCallTarget(method_id=member_target.method_id)
    if isinstance(member_target, ResolvedInterfaceMethodMemberTarget):
        return ResolvedInterfaceMethodCallTarget(
            interface_id=member_target.interface_id, method_id=member_target.method_id, access=member_target.access
        )
    if isinstance(member_target, ResolvedInstanceMethodMemberTarget):
        return ResolvedInstanceMethodCallTarget(method_id=member_target.method_id, access=member_target.access)

    return None


def _resolve_selected_constructor_id(
    typecheck_ctx: TypeCheckContext,
    class_type_name: str,
    expr: CallExpr,
) -> ConstructorId:
    class_info = lookup_class_by_type_name(typecheck_ctx, class_type_name)
    if class_info is None:
        raise ValueError(f"Unknown class '{class_type_name}' for constructor call lowering")

    arg_types = [infer_expression_type(typecheck_ctx, arg_expr) for arg_expr in expr.arguments]
    constructor_info = select_constructor_overload(
        typecheck_ctx,
        class_info,
        arg_types,
        expr.span,
        TypeInfo(name=class_type_name, kind="reference"),
    )
    owner_module, class_name = _split_class_type_name(typecheck_ctx, class_type_name)
    return ConstructorId(module_path=owner_module, class_name=class_name, ordinal=constructor_info.ordinal)


def _split_class_type_name(typecheck_ctx: TypeCheckContext, class_type_name: str) -> tuple[tuple[str, ...], str]:
    if "::" in class_type_name:
        owner_dotted, class_name = class_type_name.split("::", 1)
        return tuple(owner_dotted.split(".")), class_name
    module_path = typecheck_ctx.module_path
    if module_path is None:
        raise ValueError(f"Cannot resolve constructor owner for unqualified class '{class_type_name}'")
    return module_path, class_type_name


def _class_type_name_for_module_member(class_id) -> str:
    owner_dotted = ".".join(class_id.module_path)
    return f"{owner_dotted}::{class_id.name}"
