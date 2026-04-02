from __future__ import annotations

from compiler.common.span import SourceSpan
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import ClassInfo, ConstructorInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.relations import (
    canonicalize_reference_type_name,
    is_assignable,
    require_assignable,
    type_infos_equal,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner


def callable_type_from_signature(name: str, signature: FunctionSig) -> TypeInfo:
    return TypeInfo(name=name, kind="callable", callable_params=signature.params, callable_return=signature.return_type)


def class_type_name_from_callable(callable_name: str) -> str:
    if not callable_name.startswith("__class__:"):
        raise ValueError(f"invalid class callable name: {callable_name}")
    payload = callable_name[len("__class__:") :]
    if ":" not in payload:
        return payload
    owner_dotted, class_name = payload.rsplit(":", 1)
    return f"{owner_dotted}::{class_name}"


def check_call_argument_types(
    ctx: TypeCheckContext,
    params: list[TypeInfo],
    arg_types: list[TypeInfo],
    arg_spans: list[SourceSpan],
    span: SourceSpan,
) -> None:
    if len(params) != len(arg_types):
        raise TypeCheckError(f"Expected {len(params)} arguments, got {len(arg_types)}", span)

    for param_type, arg_type, arg_span in zip(params, arg_types, arg_spans):
        require_assignable(ctx, param_type, arg_type, arg_span)


def _require_constructor_visible(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    constructor_info: ConstructorInfo,
    result_type: TypeInfo,
    span: SourceSpan,
) -> None:
    if not constructor_info.is_private:
        return

    owner_canonical = canonicalize_reference_type_name(ctx, result_type.name)
    if ctx.current_private_owner_type != owner_canonical:
        raise TypeCheckError(f"Constructor for class '{class_info.name}' is private", span)


def _qualified_constructor_params(
    ctx: TypeCheckContext, constructor_info: ConstructorInfo, result_type: TypeInfo
) -> list[TypeInfo]:
    return [qualify_member_type_for_owner(ctx, param_type, result_type.name) for param_type in constructor_info.params]


def _constructor_signature_text(class_info: ClassInfo, params: list[TypeInfo]) -> str:
    params_text = ", ".join(param.name for param in params)
    return f"{class_info.name}({params_text})"


def _argument_types_text(arg_types: list[TypeInfo]) -> str:
    return ", ".join(arg_type.name for arg_type in arg_types)


def _constructor_is_applicable(
    ctx: TypeCheckContext,
    params: list[TypeInfo],
    arg_types: list[TypeInfo],
) -> bool:
    if len(params) != len(arg_types):
        return False
    return all(is_assignable(ctx, param_type, arg_type) for param_type, arg_type in zip(params, arg_types))


def _constructor_is_more_specific(
    ctx: TypeCheckContext,
    left_params: list[TypeInfo],
    right_params: list[TypeInfo],
) -> bool:
    if len(left_params) != len(right_params):
        return False

    any_strict = False
    for left_param, right_param in zip(left_params, right_params):
        if not is_assignable(ctx, right_param, left_param):
            return False
        if not type_infos_equal(ctx, left_param, right_param):
            any_strict = True
    return any_strict


def _select_constructor_overload(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    arg_types: list[TypeInfo],
    span: SourceSpan,
    result_type: TypeInfo,
) -> tuple[ConstructorInfo, list[TypeInfo]]:
    if len(class_info.constructors) == 1:
        constructor_info = class_info.constructors[0]
        return constructor_info, _qualified_constructor_params(ctx, constructor_info, result_type)

    candidates = [
        (constructor_info, _qualified_constructor_params(ctx, constructor_info, result_type))
        for constructor_info in class_info.constructors
    ]
    applicable_candidates = [
        (constructor_info, params)
        for constructor_info, params in candidates
        if _constructor_is_applicable(ctx, params, arg_types)
    ]

    if not applicable_candidates:
        arg_types_text = _argument_types_text(arg_types)
        candidate_text = ", ".join(
            _constructor_signature_text(class_info, params) for _constructor_info, params in candidates
        )
        raise TypeCheckError(
            f"No constructor overload for class '{class_info.name}' matches argument types ({arg_types_text}); candidates: {candidate_text}",
            span,
        )

    most_specific_candidates = [
        (candidate_info, candidate_params)
        for candidate_info, candidate_params in applicable_candidates
        if all(
            candidate_info == other_info
            or _constructor_is_more_specific(ctx, candidate_params, other_params)
            for other_info, other_params in applicable_candidates
        )
    ]

    if len(most_specific_candidates) != 1:
        arg_types_text = _argument_types_text(arg_types)
        candidate_text = ", ".join(
            _constructor_signature_text(class_info, params)
            for _constructor_info, params in applicable_candidates
        )
        raise TypeCheckError(
            f"Ambiguous constructor call for class '{class_info.name}' with argument types ({arg_types_text}); candidates: {candidate_text}",
            span,
        )

    return most_specific_candidates[0]


def select_constructor_overload(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    arg_types: list[TypeInfo],
    span: SourceSpan,
    result_type: TypeInfo,
) -> ConstructorInfo:
    constructor_info, _constructor_params = _select_constructor_overload(
        ctx,
        class_info,
        arg_types,
        span,
        result_type,
    )
    return constructor_info


def infer_constructor_call_type(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    arg_types: list[TypeInfo],
    arg_spans: list[SourceSpan],
    span: SourceSpan,
    result_type: TypeInfo,
) -> TypeInfo:
    constructor_info, constructor_params = _select_constructor_overload(ctx, class_info, arg_types, span, result_type)
    _require_constructor_visible(ctx, class_info, constructor_info, result_type, span)
    check_call_argument_types(ctx, constructor_params, arg_types, arg_spans, span)
    return result_type
