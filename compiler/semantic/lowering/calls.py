from __future__ import annotations

from dataclasses import dataclass

from compiler.frontend.ast_nodes import CallExpr, Expression, FieldAccessExpr, IdentifierExpr
from compiler.semantic.symbols import ConstructorId, InterfaceId, InterfaceMethodId, MethodId, ProgramSymbolIndex
from compiler.typecheck.call_helpers import class_type_name_from_callable
from compiler.typecheck.calls import infer_call_type
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    lookup_interface_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.semantic.lowering.ids import *


@dataclass(frozen=True)
class ResolvedFunctionCallTarget:
    function_id: object


@dataclass(frozen=True)
class ResolvedConstructorCallTarget:
    constructor_id: ConstructorId


@dataclass(frozen=True)
class ResolvedStaticMethodCallTarget:
    method_id: MethodId


@dataclass(frozen=True)
class ResolvedInstanceMethodCallTarget:
    method_id: MethodId
    receiver: Expression
    receiver_type_name: str


@dataclass(frozen=True)
class ResolvedInterfaceMethodCallTarget:
    interface_id: InterfaceId
    method_id: InterfaceMethodId
    receiver: Expression
    receiver_type_name: str


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

    name = expr.callee.name
    if name in typecheck_ctx.functions:
        return ResolvedFunctionCallTarget(function_id=function_id_for_local_name(typecheck_ctx, symbol_index, name))

    imported_function = resolve_imported_function_sig(typecheck_ctx, name, expr.callee.span)
    if imported_function is not None:
        return ResolvedFunctionCallTarget(function_id=function_id_for_imported_name(typecheck_ctx, symbol_index, name))

    imported_class_name = resolve_imported_class_name(typecheck_ctx, name, expr.callee.span)
    if name in typecheck_ctx.classes or imported_class_name is not None:
        type_name = name if imported_class_name is None else imported_class_name
        return ResolvedConstructorCallTarget(
            constructor_id=constructor_id_from_type_name(typecheck_ctx.module_path, type_name)
        )

    return None


def resolve_field_access_call_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, expr: CallExpr
) -> ResolvedCallTarget | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    module_member_target = resolve_module_member_call_target(typecheck_ctx, symbol_index, expr.callee)
    if module_member_target is not None:
        return module_member_target

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    if receiver_type.kind == "callable" and receiver_type.name.startswith("__class__:"):
        return ResolvedStaticMethodCallTarget(
            method_id=method_id_for_type_name(
                typecheck_ctx.module_path, class_type_name_from_callable(receiver_type.name), expr.callee.field_name
            )
        )

    if receiver_type.kind == "interface":
        interface_info = lookup_interface_by_type_name(typecheck_ctx, receiver_type.name)
        if interface_info is not None and expr.callee.field_name in interface_info.methods:
            return ResolvedInterfaceMethodCallTarget(
                interface_id=interface_id_for_type_name(typecheck_ctx.module_path, receiver_type.name),
                method_id=interface_method_id_for_type_name(
                    typecheck_ctx.module_path, receiver_type.name, expr.callee.field_name
                ),
                receiver=expr.callee.object_expr,
                receiver_type_name=receiver_type.name,
            )

    class_info = lookup_class_by_type_name(typecheck_ctx, receiver_type.name)
    if class_info is not None and expr.callee.field_name in class_info.methods:
        return ResolvedInstanceMethodCallTarget(
            method_id=method_id_for_type_name(typecheck_ctx.module_path, receiver_type.name, expr.callee.field_name),
            receiver=expr.callee.object_expr,
            receiver_type_name=receiver_type.name,
        )

    return None


def resolve_module_member_call_target(
    typecheck_ctx: TypeCheckContext, symbol_index: ProgramSymbolIndex, callee: FieldAccessExpr
) -> ResolvedCallTarget | None:
    module_member = resolve_module_member(typecheck_ctx, callee)
    if module_member is None:
        return None

    kind, owner_module, member_name = module_member
    if kind == "function":
        return ResolvedFunctionCallTarget(
            function_id=function_id_for_module_member(symbol_index, owner_module, member_name)
        )
    if kind == "class":
        return ResolvedConstructorCallTarget(constructor_id=constructor_id_for_module_member(owner_module, member_name))
    return None
