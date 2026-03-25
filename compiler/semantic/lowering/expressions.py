from __future__ import annotations

from compiler.common.collection_protocols import CollectionOpKind
from compiler.frontend.ast_nodes import *
from compiler.semantic.ir import *
from compiler.semantic.lowering.locals import LocalIdTracker
from compiler.semantic.symbols import ProgramSymbolIndex
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.type_resolution import resolve_type_ref

from compiler.semantic.lowering.calls import (
    ResolvedConstructorCallTarget,
    ResolvedFunctionCallTarget,
    ResolvedInstanceMethodCallTarget,
    ResolvedInterfaceMethodCallTarget,
    ResolvedStaticMethodCallTarget,
    resolve_call_target,
)
from .collections import resolve_collection_dispatch, try_lower_array_structural_call_expr, try_lower_slice_read_expr
from .literals import lower_non_string_literal_expr, lower_string_literal_expr, try_lower_string_concat_expr
from .references import lower_resolved_ref, resolve_field_access_ref_target, resolve_identifier_ref_target


def lower_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: Expression,
    local_id_tracker: LocalIdTracker | None = None,
) -> SemanticExpr:
    if isinstance(expr, IdentifierExpr):
        return _lower_identifier_expr(typecheck_ctx, symbol_index, expr, local_id_tracker)

    if isinstance(expr, LiteralExpr):
        if isinstance(expr.literal, StringLiteralValue):
            return lower_string_literal_expr(typecheck_ctx, expr, infer_expression_type(typecheck_ctx, expr).name)
        return lower_non_string_literal_expr(typecheck_ctx, expr)

    if isinstance(expr, NullExpr):
        return NullExprS(span=expr.span)

    if isinstance(expr, UnaryExpr):
        return UnaryExprS(
            operator=expr.operator,
            operand=lower_expr(typecheck_ctx, symbol_index, expr.operand, local_id_tracker),
            type_name=infer_expression_type(typecheck_ctx, expr).name,
            span=expr.span,
        )

    if isinstance(expr, BinaryExpr):
        result_type_name = infer_expression_type(typecheck_ctx, expr).name
        string_concat = try_lower_string_concat_expr(
            typecheck_ctx,
            expr,
            result_type_name,
            lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
        )
        if string_concat is not None:
            return string_concat
        return BinaryExprS(
            operator=expr.operator,
            left=lower_expr(typecheck_ctx, symbol_index, expr.left, local_id_tracker),
            right=lower_expr(typecheck_ctx, symbol_index, expr.right, local_id_tracker),
            type_name=result_type_name,
            span=expr.span,
        )

    if isinstance(expr, CastExpr):
        return CastExprS(
            operand=lower_expr(typecheck_ctx, symbol_index, expr.operand, local_id_tracker),
            target_type_name=resolve_type_ref(typecheck_ctx, expr.type_ref).name,
            type_name=infer_expression_type(typecheck_ctx, expr).name,
            span=expr.span,
        )

    if isinstance(expr, TypeTestExpr):
        return TypeTestExprS(
            operand=lower_expr(typecheck_ctx, symbol_index, expr.operand, local_id_tracker),
            target_type_name=resolve_type_ref(typecheck_ctx, expr.type_ref).name,
            type_name=infer_expression_type(typecheck_ctx, expr).name,
            span=expr.span,
        )

    if isinstance(expr, ArrayCtorExpr):
        return _lower_array_ctor_expr(typecheck_ctx, symbol_index, expr, local_id_tracker)

    if isinstance(expr, FieldAccessExpr):
        return _lower_field_access_expr(typecheck_ctx, symbol_index, expr, local_id_tracker)

    if isinstance(expr, IndexExpr):
        return _lower_index_expr(typecheck_ctx, symbol_index, expr, local_id_tracker)

    if isinstance(expr, CallExpr):
        return lower_call_expr(
            typecheck_ctx,
            symbol_index,
            expr,
            infer_expression_type(typecheck_ctx, expr).name,
            local_id_tracker,
        )

    raise TypeError(f"Unsupported expression for semantic lowering: {type(expr).__name__}")


def lower_call_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: CallExpr,
    result_type_name: str,
    local_id_tracker: LocalIdTracker | None = None,
) -> SemanticExpr:
    array_structural_expr = try_lower_array_structural_call_expr(
        typecheck_ctx,
        expr,
        result_type_name,
        lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
    )
    if array_structural_expr is not None:
        return array_structural_expr

    slice_read = try_lower_slice_read_expr(
        typecheck_ctx,
        expr,
        result_type_name,
        lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
    )
    if slice_read is not None:
        return slice_read

    resolved_target = resolve_call_target(typecheck_ctx, symbol_index, expr)
    args = [lower_expr(typecheck_ctx, symbol_index, arg, local_id_tracker) for arg in expr.arguments]

    if isinstance(resolved_target, ResolvedFunctionCallTarget):
        return FunctionCallExpr(
            function_id=resolved_target.function_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, ResolvedConstructorCallTarget):
        return ConstructorCallExpr(
            constructor_id=resolved_target.constructor_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, ResolvedStaticMethodCallTarget):
        return StaticMethodCallExpr(
            method_id=resolved_target.method_id, args=args, type_name=result_type_name, span=expr.span
        )

    if isinstance(resolved_target, ResolvedInstanceMethodCallTarget):
        return InstanceMethodCallExpr(
            method_id=resolved_target.method_id,
            receiver=lower_expr(typecheck_ctx, symbol_index, resolved_target.receiver, local_id_tracker),
            receiver_type_name=resolved_target.receiver_type_name,
            args=args,
            type_name=result_type_name,
            span=expr.span,
        )

    if isinstance(resolved_target, ResolvedInterfaceMethodCallTarget):
        return InterfaceMethodCallExpr(
            interface_id=resolved_target.interface_id,
            method_id=resolved_target.method_id,
            receiver=lower_expr(typecheck_ctx, symbol_index, resolved_target.receiver, local_id_tracker),
            receiver_type_name=resolved_target.receiver_type_name,
            args=args,
            type_name=result_type_name,
            span=expr.span,
        )

    return CallableValueCallExpr(
        callee=lower_expr(typecheck_ctx, symbol_index, resolved_target.callee, local_id_tracker),
        args=args,
        type_name=result_type_name,
        span=expr.span,
    )


def _lower_identifier_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: IdentifierExpr,
    local_id_tracker: LocalIdTracker | None,
) -> SemanticExpr:
    return lower_resolved_ref(
        resolve_identifier_ref_target(typecheck_ctx, symbol_index, expr, local_id_tracker),
        infer_expression_type(typecheck_ctx, expr).name,
        expr.span,
        lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
    )


def _lower_field_access_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: FieldAccessExpr,
    local_id_tracker: LocalIdTracker | None,
) -> SemanticExpr:
    return lower_resolved_ref(
        resolve_field_access_ref_target(typecheck_ctx, symbol_index, expr),
        infer_expression_type(typecheck_ctx, expr).name,
        expr.span,
        lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
    )


def _lower_array_ctor_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: ArrayCtorExpr,
    local_id_tracker: LocalIdTracker | None,
) -> ArrayCtorExprS:
    array_type = resolve_type_ref(typecheck_ctx, expr.element_type_ref)
    assert array_type.element_type is not None
    return ArrayCtorExprS(
        element_type_name=array_type.element_type.name,
        length_expr=lower_expr(typecheck_ctx, symbol_index, expr.length_expr, local_id_tracker),
        type_name=array_type.name,
        span=expr.span,
    )


def _lower_index_expr(
    typecheck_ctx: TypeCheckContext,
    symbol_index: ProgramSymbolIndex,
    expr: IndexExpr,
    local_id_tracker: LocalIdTracker | None,
) -> IndexReadExpr:
    target_type = infer_expression_type(typecheck_ctx, expr.object_expr)
    return IndexReadExpr(
        target=lower_expr(typecheck_ctx, symbol_index, expr.object_expr, local_id_tracker),
        index=lower_expr(typecheck_ctx, symbol_index, expr.index_expr, local_id_tracker),
        type_name=infer_expression_type(typecheck_ctx, expr).name,
        dispatch=resolve_collection_dispatch(typecheck_ctx, target_type, operation=CollectionOpKind.INDEX_GET),
        span=expr.span,
    )
