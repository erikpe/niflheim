from __future__ import annotations

from dataclasses import dataclass

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

from compiler.common.span import SourceSpan
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name, lookup_interface_by_type_name
from compiler.typecheck.relations import require_array_index_type, require_assignable
from compiler.typecheck.type_resolution import qualify_member_type_for_owner
from compiler.typecheck.visibility import require_member_visible


@dataclass(frozen=True)
class StructuralMethodBinding:
    signature: FunctionSig
    qualification_owner_type_name: str


def _lookup_structural_method_binding(
    ctx: TypeCheckContext,
    object_type: TypeInfo,
    *,
    method_name: str,
    unsupported_error: str,
    missing_error: str,
    span: SourceSpan,
) -> StructuralMethodBinding:
    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is not None:
        method_sig = class_info.methods.get(method_name)
        if method_sig is None:
            raise TypeCheckError(missing_error, span)
        method_member = class_info.method_members[method_name]
        require_member_visible(ctx, class_info, method_member.owner_class_name, method_name, "method", span)
        return StructuralMethodBinding(
            signature=method_sig,
            qualification_owner_type_name=method_member.owner_class_name,
        )

    interface_info = lookup_interface_by_type_name(ctx, object_type.name)
    if interface_info is not None:
        method_sig = interface_info.methods.get(method_name)
        if method_sig is None:
            raise TypeCheckError(missing_error, span)
        return StructuralMethodBinding(signature=method_sig, qualification_owner_type_name=object_type.name)

    raise TypeCheckError(unsupported_error, span)


def _qualified_binding_param_type(ctx: TypeCheckContext, binding: StructuralMethodBinding, index: int) -> TypeInfo:
    return qualify_member_type_for_owner(ctx, binding.signature.params[index], binding.qualification_owner_type_name)


def _qualified_binding_return_type(ctx: TypeCheckContext, binding: StructuralMethodBinding) -> TypeInfo:
    return qualify_member_type_for_owner(ctx, binding.signature.return_type, binding.qualification_owner_type_name)


def resolve_for_in_element_type(ctx: TypeCheckContext, collection_type: TypeInfo, span: SourceSpan) -> TypeInfo:
    if collection_type.element_type is not None:
        return collection_type.element_type

    iter_len_binding = _lookup_structural_method_binding(
        ctx,
        collection_type,
        method_name=COLLECTION_METHOD_ITER_LEN,
        unsupported_error=(
            f"Type '{collection_type.name}' is not iterable (missing methods 'iter_len()' and 'iter_get(i64)')"
        ),
        missing_error=f"Type '{collection_type.name}' is not iterable (missing method '{COLLECTION_METHOD_ITER_LEN}()')",
        span=span,
    )
    iter_len_sig = iter_len_binding.signature
    if iter_len_sig.is_static or len(iter_len_sig.params) != 0:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_len' must be instance method with 0 args)",
            span,
        )
    iter_len_return = _qualified_binding_return_type(ctx, iter_len_binding)
    if iter_len_return.name != TYPE_NAME_U64:
        raise TypeCheckError(f"Type '{collection_type.name}' is not iterable (method 'iter_len' must return u64)", span)

    iter_get_binding = _lookup_structural_method_binding(
        ctx,
        collection_type,
        method_name=COLLECTION_METHOD_ITER_GET,
        unsupported_error=(
            f"Type '{collection_type.name}' is not iterable (missing methods 'iter_len()' and 'iter_get(i64)')"
        ),
        missing_error=f"Type '{collection_type.name}' is not iterable (missing method '{COLLECTION_METHOD_ITER_GET}(i64)')",
        span=span,
    )
    iter_get_sig = iter_get_binding.signature
    if iter_get_sig.is_static or len(iter_get_sig.params) != 1:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_get' must be instance method with 1 arg)",
            span,
        )

    iter_get_param = _qualified_binding_param_type(ctx, iter_get_binding, 0)
    if iter_get_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{collection_type.name}' is not iterable (method 'iter_get' parameter must be i64)", span
        )

    return _qualified_binding_return_type(ctx, iter_get_binding)


def resolve_index_expression_type(
    ctx: TypeCheckContext, object_type: TypeInfo, index_type: TypeInfo, index_span: SourceSpan, span: SourceSpan
) -> TypeInfo:
    if object_type.element_type is not None:
        require_array_index_type(index_type, index_span)
        return object_type.element_type

    return _resolve_structural_get_method_result_type(ctx, object_type, index_type, index_span, span)


def _resolve_structural_get_method_result_type(
    ctx: TypeCheckContext,
    object_type: TypeInfo,
    index_type: TypeInfo,
    index_span: SourceSpan,
    span: SourceSpan,
) -> TypeInfo:
    binding = _lookup_structural_method_binding(
        ctx,
        object_type,
        method_name=COLLECTION_METHOD_INDEX_GET,
        unsupported_error=f"Type '{object_type.name}' is not indexable",
        missing_error=f"Type '{object_type.name}' is not indexable (missing method '{COLLECTION_METHOD_INDEX_GET}(K)')",
        span=span,
    )
    method_sig = binding.signature
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not indexable (method 'index_get' must be instance method)", span
        )
    if len(method_sig.params) != 1:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not indexable (method 'index_get' must take exactly 1 argument)", span
        )

    qualified_index_param = _qualified_binding_param_type(ctx, binding, 0)
    require_assignable(ctx, qualified_index_param, index_type, index_span)

    return _qualified_binding_return_type(ctx, binding)


def ensure_structural_set_method_available_for_index_assignment(
    ctx: TypeCheckContext, object_type: TypeInfo, span: SourceSpan
) -> StructuralMethodBinding:
    binding = _lookup_structural_method_binding(
        ctx,
        object_type,
        method_name=COLLECTION_METHOD_INDEX_SET,
        unsupported_error=f"Type '{object_type.name}' is not index-assignable",
        missing_error=(
            f"Type '{object_type.name}' is not index-assignable (missing method '{COLLECTION_METHOD_INDEX_SET}(K, V)')"
        ),
        span=span,
    )
    method_sig = binding.signature
    if method_sig.is_static:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must be instance method)", span
        )
    if len(method_sig.params) != 2:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must take exactly 2 arguments)",
            span,
        )

    qualified_return_type = _qualified_binding_return_type(ctx, binding)
    if qualified_return_type.name != TYPE_NAME_UNIT:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not index-assignable (method 'index_set' must return unit)", span
        )

    return binding


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
) -> StructuralMethodBinding:
    binding = ensure_structural_set_method_available_for_index_assignment(ctx, object_type, span)
    index_type = infer_expression_type(ctx, index_expr)
    qualified_index_param = _qualified_binding_param_type(ctx, binding, 0)
    require_assignable(ctx, qualified_index_param, index_type, index_expr.span)
    qualified_value_param = _qualified_binding_param_type(ctx, binding, 1)
    require_assignable(ctx, qualified_value_param, value_type, span)
    return binding


def _resolve_structural_slice_method_result_type(
    ctx: TypeCheckContext, object_type: TypeInfo, args: list[Expression], span: SourceSpan
) -> TypeInfo:
    binding = _lookup_structural_method_binding(
        ctx,
        object_type,
        method_name=COLLECTION_METHOD_SLICE_GET,
        unsupported_error=f"Type '{object_type.name}' is not sliceable",
        missing_error=f"Type '{object_type.name}' is not sliceable (missing method '{COLLECTION_METHOD_SLICE_GET}(i64, i64)')",
        span=span,
    )
    method_sig = binding.signature
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

    qualified_begin_param = _qualified_binding_param_type(ctx, binding, 0)
    qualified_end_param = _qualified_binding_param_type(ctx, binding, 1)
    if qualified_begin_param.name != TYPE_NAME_I64 or qualified_end_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not sliceable (method 'slice_get' parameters must be i64)", span
        )

    begin_arg_type = infer_expression_type(ctx, args[0])
    end_arg_type = infer_expression_type(ctx, args[1])
    require_array_index_type(begin_arg_type, args[0].span)
    require_array_index_type(end_arg_type, args[1].span)
    return _qualified_binding_return_type(ctx, binding)


def _resolve_structural_set_slice_method_result_type(
    ctx: TypeCheckContext, object_type: TypeInfo, args: list[Expression], span: SourceSpan
) -> TypeInfo:
    binding = _lookup_structural_method_binding(
        ctx,
        object_type,
        method_name=COLLECTION_METHOD_SLICE_SET,
        unsupported_error=f"Type '{object_type.name}' is not slice-assignable",
        missing_error=(
            f"Type '{object_type.name}' is not slice-assignable (missing method '{COLLECTION_METHOD_SLICE_SET}(i64, i64, U)')"
        ),
        span=span,
    )
    method_sig = binding.signature
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

    qualified_begin_param = _qualified_binding_param_type(ctx, binding, 0)
    qualified_end_param = _qualified_binding_param_type(ctx, binding, 1)
    if qualified_begin_param.name != TYPE_NAME_I64 or qualified_end_param.name != TYPE_NAME_I64:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' first two parameters must be i64)",
            span,
        )

    begin_arg_type = infer_expression_type(ctx, args[0])
    end_arg_type = infer_expression_type(ctx, args[1])
    require_array_index_type(begin_arg_type, args[0].span)
    require_array_index_type(end_arg_type, args[1].span)

    qualified_value_param = _qualified_binding_param_type(ctx, binding, 2)
    value_arg_type = infer_expression_type(ctx, args[2])
    require_assignable(ctx, qualified_value_param, value_arg_type, args[2].span)

    qualified_return_type = _qualified_binding_return_type(ctx, binding)
    if qualified_return_type.name != TYPE_NAME_UNIT:
        raise TypeCheckError(
            f"Type '{object_type.name}' is not slice-assignable (method 'slice_set' must return unit)", span
        )

    return TypeInfo(name=TYPE_NAME_UNIT, kind="primitive")


def infer_structural_special_method_call_type(
    ctx: TypeCheckContext,
    object_type: TypeInfo,
    method_name: str,
    args: list[Expression],
    span: SourceSpan,
) -> TypeInfo | None:
    if method_name == COLLECTION_METHOD_SLICE_GET:
        return _resolve_structural_slice_method_result_type(ctx, object_type, args, span)
    if method_name == COLLECTION_METHOD_SLICE_SET:
        return _resolve_structural_set_slice_method_result_type(ctx, object_type, args, span)
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
