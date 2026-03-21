from __future__ import annotations

from compiler.common.collection_protocols import (
    COLLECTION_METHOD_INDEX_GET,
    COLLECTION_METHOD_INDEX_SET,
    COLLECTION_METHOD_ITER_GET,
    COLLECTION_METHOD_ITER_LEN,
    COLLECTION_METHOD_LEN,
    COLLECTION_METHOD_SLICE_GET,
    COLLECTION_METHOD_SLICE_SET,
)
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_UNIT
from compiler.frontend.ast_nodes import Expression

from compiler.frontend.lexer import SourceSpan
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.typecheck.relations import require_array_index_type, require_assignable
from compiler.typecheck.type_resolution import qualify_member_type_for_owner
from compiler.typecheck.visibility import require_member_visible


def resolve_for_in_element_type(ctx: TypeCheckContext, collection_type: TypeInfo, span: SourceSpan) -> TypeInfo:
    if collection_type.element_type is not None:
        return collection_type.element_type

    class_info = lookup_class_by_type_name(ctx, collection_type.name)
    if class_info is None:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (missing methods 'iter_len()' and 'iter_get(i64)')", span
        )

    iter_len_sig = class_info.methods.get(COLLECTION_METHOD_ITER_LEN)
    if iter_len_sig is None:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (missing method '{COLLECTION_METHOD_ITER_LEN}()')", span
        )
    require_member_visible(ctx, class_info, collection_type.name, COLLECTION_METHOD_ITER_LEN, "method", span)
    if iter_len_sig.is_static or len(iter_len_sig.params) != 0:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_len' must be instance method with 0 args)",
            span,
        )
    iter_len_return = qualify_member_type_for_owner(ctx, iter_len_sig.return_type, collection_type.name)
    if iter_len_return.name != TYPE_NAME_U64:
        raise TypeCheckError(f"Type '{collection_type.name}' is not iterable (method 'iter_len' must return u64)", span)

    iter_get_sig = class_info.methods.get(COLLECTION_METHOD_ITER_GET)
    if iter_get_sig is None:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (missing method '{COLLECTION_METHOD_ITER_GET}(i64)')", span
        )
    require_member_visible(ctx, class_info, collection_type.name, COLLECTION_METHOD_ITER_GET, "method", span)
    if iter_get_sig.is_static or len(iter_get_sig.params) != 1:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_get' must be instance method with 1 arg)",
            span,
        )

    iter_get_param = qualify_member_type_for_owner(ctx, iter_get_sig.params[0], collection_type.name)
    if iter_get_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_get' parameter must be i64)", span
        )

    return qualify_member_type_for_owner(ctx, iter_get_sig.return_type, collection_type.name)


def resolve_index_expression_type(
    ctx: TypeCheckContext, object_type: TypeInfo, index_type: TypeInfo, index_span: SourceSpan, span: SourceSpan
) -> TypeInfo:
    if object_type.element_type is not None:
        require_array_index_type(index_type, index_span)
        return object_type.element_type

    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is not None:
        return _resolve_structural_get_method_result_type(ctx, object_type, class_info, index_type, index_span, span)

    raise TypeCheckError(f"Type '{object_type.name}' is not indexable", span)


def _resolve_structural_get_method_result_type(
    ctx: TypeCheckContext,
    object_type: TypeInfo,
    class_info: ClassInfo,
    index_type: TypeInfo,
    index_span: SourceSpan,
    span: SourceSpan,
) -> TypeInfo:
    method_sig = class_info.methods.get(COLLECTION_METHOD_INDEX_GET)
    if method_sig is None:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not indexable (missing method '{COLLECTION_METHOD_INDEX_GET}(K)')", span
        )
    require_member_visible(ctx, class_info, object_type.name, COLLECTION_METHOD_INDEX_GET, "method", span)
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not indexable (method 'index_get' must be instance method)", span
        )
    if len(method_sig.params) != 1:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not indexable (method 'index_get' must take exactly 1 argument)", span
        )

    qualified_index_param = qualify_member_type_for_owner(ctx, method_sig.params[0], object_type.name)
    require_assignable(ctx, qualified_index_param, index_type, index_span)

    return qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)


def ensure_structural_set_method_available_for_index_assignment(
    ctx: TypeCheckContext, object_type: TypeInfo, span: SourceSpan
) -> FunctionSig:
    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is None:
        raise TypeCheckError(f"Type '{object_type.name}' is not index-assignable", span)

    method_sig = class_info.methods.get(COLLECTION_METHOD_INDEX_SET)
    if method_sig is None:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (missing method '{COLLECTION_METHOD_INDEX_SET}(K, V)')",
            span,
        )
    require_member_visible(ctx, class_info, object_type.name, COLLECTION_METHOD_INDEX_SET, "method", span)
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must be instance method)", span
        )
    if len(method_sig.params) != 2:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must take exactly 2 arguments)",
            span,
        )

    qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)
    if qualified_return_type.name != TYPE_NAME_UNIT:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must return unit)", span
        )

    return method_sig


def ensure_index_assignment(
    ctx: TypeCheckContext, object_type: TypeInfo, index_expr: Expression, value_type: TypeInfo, span: SourceSpan
) -> None:
    if object_type.element_type is not None:
        index_type = infer_expression_type(ctx, index_expr)
        require_array_index_type(index_type, index_expr.span)
        require_assignable(ctx, object_type.element_type, value_type, span)
        return

    method_sig = _ensure_structural_set_method_for_index_assignment(ctx, object_type, index_expr, value_type, span)
    _ = method_sig


def _ensure_structural_set_method_for_index_assignment(
    ctx: TypeCheckContext, object_type: TypeInfo, index_expr: Expression, value_type: TypeInfo, span: SourceSpan
) -> FunctionSig:
    method_sig = ensure_structural_set_method_available_for_index_assignment(ctx, object_type, span)
    index_type = infer_expression_type(ctx, index_expr)
    qualified_index_param = qualify_member_type_for_owner(ctx, method_sig.params[0], object_type.name)
    require_assignable(ctx, qualified_index_param, index_type, index_expr.span)
    qualified_value_param = qualify_member_type_for_owner(ctx, method_sig.params[1], object_type.name)
    require_assignable(ctx, qualified_value_param, value_type, span)
    return method_sig


def _resolve_structural_slice_method_result_type(
    ctx: TypeCheckContext, object_type: TypeInfo, class_info: ClassInfo, args: list[Expression], span: SourceSpan
) -> TypeInfo:
    method_sig = class_info.methods.get(COLLECTION_METHOD_SLICE_GET)
    if method_sig is None:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not sliceable (missing method '{COLLECTION_METHOD_SLICE_GET}(i64, i64)')",
            span,
        )
    require_member_visible(ctx, class_info, object_type.name, COLLECTION_METHOD_SLICE_GET, "method", span)
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not sliceable (method 'slice_get' must be instance method)", span
        )
    if len(method_sig.params) != 2:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not sliceable (method 'slice_get' must take exactly 2 arguments)", span
        )
    if len(args) != 2:
        raise TypeCheckError(f"Expected 2 arguments, got {len(args)}", span)

    qualified_begin_param = qualify_member_type_for_owner(ctx, method_sig.params[0], object_type.name)
    qualified_end_param = qualify_member_type_for_owner(ctx, method_sig.params[1], object_type.name)
    if qualified_begin_param.name != TYPE_NAME_I64 or qualified_end_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not sliceable (method 'slice_get' parameters must be i64)", span
        )

    begin_arg_type = infer_expression_type(ctx, args[0])
    end_arg_type = infer_expression_type(ctx, args[1])
    require_array_index_type(begin_arg_type, args[0].span)
    require_array_index_type(end_arg_type, args[1].span)
    return qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)


def _resolve_structural_set_slice_method_result_type(
    ctx: TypeCheckContext, object_type: TypeInfo, class_info: ClassInfo, args: list[Expression], span: SourceSpan
) -> TypeInfo:
    method_sig = class_info.methods.get(COLLECTION_METHOD_SLICE_SET)
    if method_sig is None:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (missing method '{COLLECTION_METHOD_SLICE_SET}(i64, i64, U)')",
            span,
        )
    require_member_visible(ctx, class_info, object_type.name, COLLECTION_METHOD_SLICE_SET, "method", span)
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must be instance method)", span
        )
    if len(method_sig.params) != 3:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must take exactly 3 arguments)",
            span,
        )
    if len(args) != 3:
        raise TypeCheckError(f"Expected 3 arguments, got {len(args)}", span)

    qualified_begin_param = qualify_member_type_for_owner(ctx, method_sig.params[0], object_type.name)
    qualified_end_param = qualify_member_type_for_owner(ctx, method_sig.params[1], object_type.name)
    if qualified_begin_param.name != TYPE_NAME_I64 or qualified_end_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' first two parameters must be i64)",
            span,
        )

    begin_arg_type = infer_expression_type(ctx, args[0])
    end_arg_type = infer_expression_type(ctx, args[1])
    require_array_index_type(begin_arg_type, args[0].span)
    require_array_index_type(end_arg_type, args[1].span)

    qualified_value_param = qualify_member_type_for_owner(ctx, method_sig.params[2], object_type.name)
    value_arg_type = infer_expression_type(ctx, args[2])
    require_assignable(ctx, qualified_value_param, value_arg_type, args[2].span)

    qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)
    if qualified_return_type.name != TYPE_NAME_UNIT:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must return unit)", span
        )

    return TypeInfo(name=TYPE_NAME_UNIT, kind="primitive")


def infer_structural_special_method_call_type(
    ctx: TypeCheckContext,
    object_type: TypeInfo,
    class_info: ClassInfo,
    method_name: str,
    args: list[Expression],
    span: SourceSpan,
) -> TypeInfo | None:
    if method_name == COLLECTION_METHOD_SLICE_GET:
        return _resolve_structural_slice_method_result_type(ctx, object_type, class_info, args, span)
    if method_name == COLLECTION_METHOD_SLICE_SET:
        return _resolve_structural_set_slice_method_result_type(ctx, object_type, class_info, args, span)
    return None


def infer_array_method_call_type(
    ctx: TypeCheckContext, object_type: TypeInfo, method_name: str, args: list[Expression], span: SourceSpan
) -> TypeInfo:
    if method_name == COLLECTION_METHOD_LEN:
        if args:
            raise TypeCheckError(f"Expected 0 arguments, got {len(args)}", span)
        return TypeInfo(name=TYPE_NAME_U64, kind="primitive")
    if method_name == COLLECTION_METHOD_ITER_LEN:
        if args:
            raise TypeCheckError(f"Expected 0 arguments, got {len(args)}", span)
        return TypeInfo(name=TYPE_NAME_U64, kind="primitive")
    if method_name == COLLECTION_METHOD_INDEX_GET:
        if len(args) != 1:
            raise TypeCheckError(f"Expected 1 arguments, got {len(args)}", span)
        index_type = infer_expression_type(ctx, args[0])
        require_array_index_type(index_type, args[0].span)
        return object_type.element_type
    if method_name == COLLECTION_METHOD_ITER_GET:
        if len(args) != 1:
            raise TypeCheckError(f"Expected 1 arguments, got {len(args)}", span)
        index_type = infer_expression_type(ctx, args[0])
        require_array_index_type(index_type, args[0].span)
        return object_type.element_type
    if method_name == COLLECTION_METHOD_INDEX_SET:
        if len(args) != 2:
            raise TypeCheckError(f"Expected 2 arguments, got {len(args)}", span)
        index_type = infer_expression_type(ctx, args[0])
        require_array_index_type(index_type, args[0].span)
        value_type = infer_expression_type(ctx, args[1])
        require_assignable(ctx, object_type.element_type, value_type, args[1].span)
        return TypeInfo(name=TYPE_NAME_UNIT, kind="primitive")
    if method_name == COLLECTION_METHOD_SLICE_GET:
        if len(args) != 2:
            raise TypeCheckError(f"Expected 2 arguments, got {len(args)}", span)
        start_type = infer_expression_type(ctx, args[0])
        end_type = infer_expression_type(ctx, args[1])
        require_array_index_type(start_type, args[0].span)
        require_array_index_type(end_type, args[1].span)
        return object_type
    if method_name == COLLECTION_METHOD_SLICE_SET:
        if len(args) != 3:
            raise TypeCheckError(f"Expected 3 arguments, got {len(args)}", span)
        start_type = infer_expression_type(ctx, args[0])
        end_type = infer_expression_type(ctx, args[1])
        require_array_index_type(start_type, args[0].span)
        require_array_index_type(end_type, args[1].span)
        value_type = infer_expression_type(ctx, args[2])
        require_assignable(ctx, object_type, value_type, args[2].span)
        return TypeInfo(name=TYPE_NAME_UNIT, kind="primitive")

    raise TypeCheckError(f"Array type '{object_type.name}' has no method '{method_name}'", span)
