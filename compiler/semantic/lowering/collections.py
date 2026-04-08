from __future__ import annotations

from collections.abc import Callable

from compiler.common.collection_protocols import *
from compiler.common.type_names import *
from compiler.frontend.ast_nodes import CallExpr, ExprStmt, Expression, FieldAccessExpr
from compiler.semantic.ir import *
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.lowering.ids import (
    class_id_from_type_name,
    interface_id_for_type_name,
    interface_method_id_for_type_name,
    method_id_for_type_name,
)
from compiler.semantic.types import semantic_type_canonical_name
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name, lookup_interface_by_type_name


LowerExpr = Callable[[Expression], SemanticExpr]


def try_lower_array_structural_call_expr(
    typecheck_ctx: TypeCheckContext,
    expr: CallExpr,
    _result_type_name: str,
    result_type_ref: SemanticTypeRef,
    *,
    lower_expr: LowerExpr,
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
            type_ref=result_type_ref,
            dispatch=runtime_dispatch_for_array_operation(typecheck_ctx, receiver_type, op_kind),
            span=expr.span,
        )

    if op_kind is CollectionOpKind.SLICE_GET:
        if len(expr.arguments) != 2:
            return None
        return SliceReadExpr(
            target=lower_expr(expr.callee.object_expr),
            begin=lower_expr(expr.arguments[0]),
            end=lower_expr(expr.arguments[1]),
            type_ref=result_type_ref,
            dispatch=runtime_dispatch_for_array_operation(typecheck_ctx, receiver_type, op_kind),
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
            value_type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, infer_expression_type(typecheck_ctx, expr.arguments[2])),
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
            value_type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, receiver_type.element_type),
            dispatch=runtime_dispatch_for_array_operation(typecheck_ctx, receiver_type, CollectionOpKind.INDEX_SET),
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
            value_type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, infer_expression_type(typecheck_ctx, expr.arguments[2])),
            dispatch=runtime_dispatch_for_array_operation(typecheck_ctx, receiver_type, CollectionOpKind.SLICE_SET),
            span=expr.span,
        ),
        value=lower_expr(expr.arguments[2]),
        span=stmt.span,
    )


def try_lower_slice_read_expr(
    typecheck_ctx: TypeCheckContext,
    expr: CallExpr,
    _result_type_name: str,
    result_type_ref: SemanticTypeRef,
    *,
    lower_expr: LowerExpr,
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
        type_ref=result_type_ref,
        dispatch=resolve_collection_dispatch(typecheck_ctx, receiver_type, operation=CollectionOpKind.SLICE_GET),
        span=expr.span,
    )


def resolve_collection_dispatch(
    typecheck_ctx: TypeCheckContext, receiver_type: TypeInfo, *, operation: CollectionOpKind
) -> SemanticDispatch:
    if receiver_type.element_type is not None:
        return runtime_dispatch_for_array_operation(typecheck_ctx, receiver_type, operation)

    receiver_type_ref = semantic_type_ref_from_checked_type(typecheck_ctx, receiver_type)
    receiver_type_name = semantic_type_canonical_name(receiver_type_ref)

    interface_info = lookup_interface_by_type_name(typecheck_ctx, receiver_type_name)
    if interface_info is not None:
        method_name = collection_method_name(operation)
        if method_name not in interface_info.methods:
            raise ValueError(f"Missing structural method '{method_name}' on interface '{receiver_type_name}'")
        return InterfaceDispatch(
            interface_id=interface_id_for_type_name(typecheck_ctx.module_path, receiver_type_name),
            method_id=interface_method_id_for_type_name(typecheck_ctx.module_path, receiver_type_name, method_name),
        )

    class_info = lookup_class_by_type_name(typecheck_ctx, receiver_type_name)
    if class_info is None:
        raise ValueError(
            f"Cannot resolve structural method '{collection_method_name(operation)}' on non-collection type '{receiver_type_name}'"
        )

    method_name = collection_method_name(operation)
    method_member = class_info.method_members.get(method_name)
    if method_member is None:
        raise ValueError(f"Missing structural method '{method_name}' on type '{receiver_type_name}'")
    if method_member.signature.is_static:
        raise ValueError(f"Expected instance structural method '{method_name}' on type '{receiver_type_name}'")

    selected_method_id = method_id_for_type_name(typecheck_ctx.module_path, method_member.owner_class_name, method_name)
    if method_member.slot_owner_class_name is not None:
        return VirtualMethodDispatch(
            receiver_class_id=class_id_from_type_name(typecheck_ctx.module_path, receiver_type_name),
            slot_owner_class_id=class_id_from_type_name(typecheck_ctx.module_path, method_member.slot_owner_class_name),
            method_name=method_name,
            selected_method_id=selected_method_id,
        )
    return MethodDispatch(method_id=selected_method_id)


def runtime_dispatch_for_array_operation(
    typecheck_ctx: TypeCheckContext, receiver_type: TypeInfo, operation: CollectionOpKind
) -> RuntimeDispatch:
    if operation in {CollectionOpKind.LEN, CollectionOpKind.ITER_LEN}:
        return RuntimeDispatch(operation=operation)
    element_type = receiver_type.element_type
    if element_type is None:
        raise ValueError(f"Array runtime dispatch requires array receiver type, got '{receiver_type.name}'")
    return RuntimeDispatch(
        operation=operation,
        runtime_kind=array_runtime_kind(semantic_type_ref_from_checked_type(typecheck_ctx, element_type)),
    )


def array_runtime_kind(element_type_ref: SemanticTypeRef) -> ArrayRuntimeKind:
    element_type_name = semantic_type_canonical_name(element_type_ref)
    if element_type_name == TYPE_NAME_UNIT:
        raise ValueError("Array runtime kind is not defined for unit elements")
    return array_runtime_kind_for_element_type_name(element_type_name)
