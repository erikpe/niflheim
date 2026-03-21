from __future__ import annotations

from collections.abc import Callable

from compiler.common.collection_protocols import *
from compiler.common.type_names import *
from compiler.frontend.ast_nodes import CallExpr, ExprStmt, Expression, FieldAccessExpr
from compiler.semantic.ir import *
from .ids import resolve_instance_method_id
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo


LowerExpr = Callable[[Expression], SemanticExpr]


def try_lower_array_structural_call_expr(
    typecheck_ctx: TypeCheckContext, expr: CallExpr, result_type_name: str, *, lower_expr: LowerExpr
) -> SemanticExpr | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    op_kind = collection_op_from_method_name(expr.callee.field_name)
    if op_kind is None:
        return None

    if op_kind in {CollectionOpKind.LEN, CollectionOpKind.ITER_LEN}:
        if expr.arguments:
            return None
        return ArrayLenExpr(target=lower_expr(expr.callee.object_expr), span=expr.span)

    if op_kind in {CollectionOpKind.INDEX_GET, CollectionOpKind.ITER_GET}:
        if len(expr.arguments) != 1:
            return None
        return IndexReadExpr(
            target=lower_expr(expr.callee.object_expr),
            index=lower_expr(expr.arguments[0]),
            type_name=result_type_name,
            dispatch=runtime_dispatch_for_array_operation(receiver_type, op_kind),
            span=expr.span,
        )

    if op_kind is CollectionOpKind.SLICE_GET:
        if len(expr.arguments) != 2:
            return None
        return SliceReadExpr(
            target=lower_expr(expr.callee.object_expr),
            begin=lower_expr(expr.arguments[0]),
            end=lower_expr(expr.arguments[1]),
            type_name=result_type_name,
            dispatch=runtime_dispatch_for_array_operation(receiver_type, op_kind),
            span=expr.span,
        )

    return None


def try_lower_slice_assign_stmt(
    typecheck_ctx: TypeCheckContext, stmt: ExprStmt, *, lower_expr: LowerExpr
) -> SemanticAssign | None:
    array_index_assign = try_lower_array_index_assign_stmt(typecheck_ctx, stmt, lower_expr=lower_expr)
    if array_index_assign is not None:
        return array_index_assign

    array_slice_assign = try_lower_array_slice_assign_stmt(typecheck_ctx, stmt, lower_expr=lower_expr)
    if array_slice_assign is not None:
        return array_slice_assign

    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if (
        collection_op_from_method_name(expr.callee.field_name) is not CollectionOpKind.SLICE_SET
        or len(expr.arguments) != 3
    ):
        return None

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    return SemanticAssign(
        target=SliceLValue(
            target=lower_expr(expr.callee.object_expr),
            begin=lower_expr(expr.arguments[0]),
            end=lower_expr(expr.arguments[1]),
            value_type_name=infer_expression_type(typecheck_ctx, expr.arguments[2]).name,
            dispatch=resolve_collection_dispatch(typecheck_ctx, receiver_type, operation=CollectionOpKind.SLICE_SET),
            span=expr.span,
        ),
        value=lower_expr(expr.arguments[2]),
        span=stmt.span,
    )


def try_lower_array_index_assign_stmt(
    typecheck_ctx: TypeCheckContext, stmt: ExprStmt, *, lower_expr: LowerExpr
) -> SemanticAssign | None:
    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if (
        collection_op_from_method_name(expr.callee.field_name) is not CollectionOpKind.INDEX_SET
        or len(expr.arguments) != 2
    ):
        return None

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    return SemanticAssign(
        target=IndexLValue(
            target=lower_expr(expr.callee.object_expr),
            index=lower_expr(expr.arguments[0]),
            value_type_name=receiver_type.element_type.name,
            dispatch=runtime_dispatch_for_array_operation(receiver_type, CollectionOpKind.INDEX_SET),
            span=expr.span,
        ),
        value=lower_expr(expr.arguments[1]),
        span=stmt.span,
    )


def try_lower_array_slice_assign_stmt(
    typecheck_ctx: TypeCheckContext, stmt: ExprStmt, *, lower_expr: LowerExpr
) -> SemanticAssign | None:
    expr = stmt.expression
    if not isinstance(expr, CallExpr):
        return None
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if (
        collection_op_from_method_name(expr.callee.field_name) is not CollectionOpKind.SLICE_SET
        or len(expr.arguments) != 3
    ):
        return None

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    if receiver_type.element_type is None:
        return None

    return SemanticAssign(
        target=SliceLValue(
            target=lower_expr(expr.callee.object_expr),
            begin=lower_expr(expr.arguments[0]),
            end=lower_expr(expr.arguments[1]),
            value_type_name=infer_expression_type(typecheck_ctx, expr.arguments[2]).name,
            dispatch=runtime_dispatch_for_array_operation(receiver_type, CollectionOpKind.SLICE_SET),
            span=expr.span,
        ),
        value=lower_expr(expr.arguments[2]),
        span=stmt.span,
    )


def try_lower_slice_read_expr(
    typecheck_ctx: TypeCheckContext, expr: CallExpr, result_type_name: str, *, lower_expr: LowerExpr
) -> SliceReadExpr | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None
    if (
        collection_op_from_method_name(expr.callee.field_name) is not CollectionOpKind.SLICE_GET
        or len(expr.arguments) != 2
    ):
        return None

    receiver_type = infer_expression_type(typecheck_ctx, expr.callee.object_expr)
    return SliceReadExpr(
        target=lower_expr(expr.callee.object_expr),
        begin=lower_expr(expr.arguments[0]),
        end=lower_expr(expr.arguments[1]),
        type_name=result_type_name,
        dispatch=resolve_collection_dispatch(typecheck_ctx, receiver_type, operation=CollectionOpKind.SLICE_GET),
        span=expr.span,
    )


def resolve_collection_dispatch(
    typecheck_ctx: TypeCheckContext, receiver_type: TypeInfo, *, operation: CollectionOpKind
) -> SemanticDispatch:
    if receiver_type.element_type is not None:
        return runtime_dispatch_for_array_operation(receiver_type, operation)

    method_id = resolve_instance_method_id(typecheck_ctx, receiver_type.name, collection_method_name(operation))
    assert method_id is not None
    return MethodDispatch(method_id=method_id)


def runtime_dispatch_for_array_operation(receiver_type: TypeInfo, operation: CollectionOpKind) -> RuntimeDispatch:
    if operation in {CollectionOpKind.LEN, CollectionOpKind.ITER_LEN}:
        return RuntimeDispatch(operation=operation)
    element_type = receiver_type.element_type
    if element_type is None:
        raise ValueError(f"Array runtime dispatch requires array receiver type, got '{receiver_type.name}'")
    return RuntimeDispatch(operation=operation, runtime_kind=array_runtime_kind(element_type.name))


def array_runtime_kind(element_type_name: str) -> ArrayRuntimeKind:
    if element_type_name == TYPE_NAME_I64:
        return ArrayRuntimeKind.I64
    if element_type_name == TYPE_NAME_U64:
        return ArrayRuntimeKind.U64
    if element_type_name == TYPE_NAME_U8:
        return ArrayRuntimeKind.U8
    if element_type_name == TYPE_NAME_BOOL:
        return ArrayRuntimeKind.BOOL
    if element_type_name == TYPE_NAME_DOUBLE:
        return ArrayRuntimeKind.DOUBLE
    if element_type_name == TYPE_NAME_UNIT:
        raise ValueError("Array runtime kind is not defined for unit elements")
    return ArrayRuntimeKind.REF
