from __future__ import annotations

from compiler.lexer import SourceSpan
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.relations import canonicalize_reference_type_name, require_assignable


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


def infer_constructor_call_type(
    ctx: TypeCheckContext,
    class_info: ClassInfo,
    arg_types: list[TypeInfo],
    arg_spans: list[SourceSpan],
    span: SourceSpan,
    result_type: TypeInfo,
) -> TypeInfo:
    if class_info.constructor_is_private:
        owner_canonical = canonicalize_reference_type_name(ctx, result_type.name)
        if ctx.current_private_owner_type != owner_canonical:
            raise TypeCheckError(f"Constructor for class '{class_info.name}' is private", span)

    ctor_params = [class_info.fields[field_name] for field_name in class_info.constructor_param_order]
    check_call_argument_types(ctx, ctor_params, arg_types, arg_spans, span)
    return result_type
