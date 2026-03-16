from __future__ import annotations

from compiler.typecheck.context import TypeCheckContext
from compiler.lexer import SourceSpan
from compiler.typecheck.model import TypeCheckError, TypeInfo


def canonicalize_reference_type_name(
    ctx: TypeCheckContext,
    type_name: str,
) -> str:
    if "::" in type_name:
        return type_name
    if ctx.module_path is None:
        return type_name
    if type_name not in ctx.classes:
        return type_name
    owner_dotted = ".".join(ctx.module_path)
    return f"{owner_dotted}::{type_name}"


def type_names_equal(
    ctx: TypeCheckContext,
    left: str,
    right: str,
) -> bool:
    if left == right:
        return True
    return canonicalize_reference_type_name(ctx, left) == canonicalize_reference_type_name(ctx, right)


def type_infos_equal(
    ctx: TypeCheckContext,
    left: TypeInfo,
    right: TypeInfo,
) -> bool:
    if left.kind == "callable" or right.kind == "callable":
        if left.kind != "callable" or right.kind != "callable":
            return False
        if left.callable_params is None or right.callable_params is None:
            return False
        if left.callable_return is None or right.callable_return is None:
            return False
        if len(left.callable_params) != len(right.callable_params):
            return False
        if not all(
            type_infos_equal(
                ctx,
                left_param,
                right_param,
            )
            for left_param, right_param in zip(left.callable_params, right.callable_params)
        ):
            return False
        return type_infos_equal(
            ctx,
            left.callable_return,
            right.callable_return,
        )

    if left.element_type is not None or right.element_type is not None:
        if left.element_type is None or right.element_type is None:
            return False
        return type_infos_equal(
            ctx,
            left.element_type,
            right.element_type,
        )

    return type_names_equal(
        ctx,
        left.name,
        right.name,
    )


def format_function_type_name(params: list[TypeInfo], return_type: TypeInfo) -> str:
    params_text = ", ".join(param.name for param in params)
    return f"fn({params_text}) -> {return_type.name}"


def display_type_name(type_info: TypeInfo) -> str:
    if type_info.kind == "callable" and type_info.callable_params is not None and type_info.callable_return is not None:
        return format_function_type_name(type_info.callable_params, type_info.callable_return)
    return type_info.name


def require_type_name(actual: TypeInfo, expected_name: str, span: SourceSpan) -> None:
    if actual.name != expected_name:
        raise TypeCheckError(f"Expected '{expected_name}', got '{actual.name}'", span)


def require_array_size_type(actual: TypeInfo, span: SourceSpan) -> None:
    if actual.name in {"u64", "i64"}:
        return
    raise TypeCheckError(f"Expected 'u64', got '{actual.name}'", span)


def require_array_index_type(actual: TypeInfo, span: SourceSpan) -> None:
    if actual.name == "i64":
        return
    raise TypeCheckError(f"Expected 'i64', got '{actual.name}'", span)


def require_assignable(
    ctx: TypeCheckContext,
    target: TypeInfo,
    value: TypeInfo,
    span: SourceSpan,
) -> None:
    if type_infos_equal(
        ctx,
        target,
        value,
    ):
        return
    if target.kind == "reference" and value.kind == "null":
        return
    if target.name == "Obj" and value.kind == "reference":
        return
    raise TypeCheckError(
        f"Cannot assign '{display_type_name(value)}' to '{display_type_name(target)}'",
        span,
    )


def is_comparable(
    ctx: TypeCheckContext,
    left: TypeInfo,
    right: TypeInfo,
) -> bool:
    if type_infos_equal(
        ctx,
        left,
        right,
    ):
        return True
    if left.kind == "reference" and right.kind == "null":
        return True
    if right.kind == "reference" and left.kind == "null":
        return True
    return False


def check_explicit_cast(
    ctx: TypeCheckContext,
    source: TypeInfo,
    target: TypeInfo,
    span: SourceSpan,
) -> None:
    if source.kind == "callable" or target.kind == "callable":
        raise TypeCheckError("Casts involving function types are not allowed in MVP", span)

    if type_infos_equal(
        ctx,
        source,
        target,
    ):
        return

    if source.kind == "primitive" and target.kind == "primitive":
        if source.name == "unit" or target.name == "unit":
            raise TypeCheckError("Casts involving 'unit' are not allowed", span)
        return

    if source.kind == "reference" and target.name == "Obj":
        return

    if source.name == "Obj" and target.kind == "reference" and target.name != "Obj":
        return

    raise TypeCheckError(
        f"Invalid cast from '{source.name}' to '{target.name}'",
        span,
    )
