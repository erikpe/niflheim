from __future__ import annotations

import compiler.codegen.types as codegen_types

from compiler.ast_nodes import (
    ArrayCtorExpr,
    BinaryExpr,
    CallExpr,
    CastExpr,
    Expression,
    FieldAccessExpr,
    IdentifierExpr,
    IndexExpr,
    LiteralExpr,
    NullExpr,
    UnaryExpr,
)
from compiler.codegen.model import (
    ARRAY_GET_RUNTIME_CALLS,
    ARRAY_SET_RUNTIME_CALLS,
    ARRAY_SET_SLICE_RUNTIME_CALLS,
    ARRAY_SLICE_RUNTIME_CALLS,
    EmitContext,
    RUNTIME_RETURN_TYPES,
    ResolvedCallTarget,
)
from compiler.codegen.strings import STR_CLASS_NAME


def _flatten_field_chain(expr: Expression) -> list[str] | None:
    if isinstance(expr, IdentifierExpr):
        return [expr.name]

    if isinstance(expr, FieldAccessExpr):
        left = _flatten_field_chain(expr.object_expr)
        if left is None:
            return None
        return [*left, expr.field_name]

    return None


def _resolve_method_call_target(
    callee: FieldAccessExpr,
    ctx: EmitContext,
) -> ResolvedCallTarget:
    receiver_expr = callee.object_expr
    if isinstance(receiver_expr, IdentifierExpr):
        receiver_type_name = ctx.layout.slot_type_names.get(receiver_expr.name)
        if receiver_type_name is None:
            codegen_types.raise_codegen_error(
                f"method receiver '{receiver_expr.name}' is not materialized in stack layout",
                span=callee.span,
            )
    elif isinstance(receiver_expr, CastExpr):
        receiver_type_name = codegen_types.type_ref_name(receiver_expr.type_ref)
    else:
        receiver_type_name = infer_expression_type_name(receiver_expr, ctx)

    method_owner_type_name = receiver_type_name
    method_name = callee.field_name

    if codegen_types.is_array_type_name(method_owner_type_name):
        element_type_name = codegen_types.array_element_type_name(method_owner_type_name, span=callee.span)
        kind = codegen_types.array_element_runtime_kind(element_type_name)
        if method_name == "len":
            return ResolvedCallTarget(name="rt_array_len", receiver_expr=receiver_expr, return_type_name="u64")
        if method_name == "iter_len":
            return ResolvedCallTarget(name="rt_array_len", receiver_expr=receiver_expr, return_type_name="u64")
        if method_name == "index_get":
            return ResolvedCallTarget(
                name=ARRAY_GET_RUNTIME_CALLS[kind],
                receiver_expr=receiver_expr,
                return_type_name=element_type_name,
            )
        if method_name == "iter_get":
            return ResolvedCallTarget(
                name=ARRAY_GET_RUNTIME_CALLS[kind],
                receiver_expr=receiver_expr,
                return_type_name=element_type_name,
            )
        if method_name == "index_set":
            return ResolvedCallTarget(
                name=ARRAY_SET_RUNTIME_CALLS[kind],
                receiver_expr=receiver_expr,
                return_type_name="unit",
            )
        if method_name == "slice_get":
            return ResolvedCallTarget(
                name=ARRAY_SLICE_RUNTIME_CALLS[kind],
                receiver_expr=receiver_expr,
                return_type_name=method_owner_type_name,
            )
        if method_name == "slice_set":
            return ResolvedCallTarget(
                name=ARRAY_SET_SLICE_RUNTIME_CALLS[kind],
                receiver_expr=receiver_expr,
                return_type_name="unit",
            )
        codegen_types.raise_codegen_error(
            f"array method-call codegen could not resolve '{method_owner_type_name}.{method_name}'",
            span=callee.span,
        )

    method_label = ctx.method_labels.get((receiver_type_name, method_name))
    if method_label is None and "::" in receiver_type_name:
        unqualified_type_name = receiver_type_name.split("::", 1)[1]
        method_label = ctx.method_labels.get((unqualified_type_name, method_name))
    if method_label is None:
        codegen_types.raise_codegen_error(
            f"method-call codegen could not resolve '{receiver_type_name}.{method_name}'",
            span=callee.span,
        )

    is_static = ctx.method_is_static.get((receiver_type_name, method_name))
    if is_static is None and "::" in receiver_type_name:
        unqualified_type_name = receiver_type_name.split("::", 1)[1]
        is_static = ctx.method_is_static.get((unqualified_type_name, method_name))
    if is_static:
        codegen_types.raise_codegen_error(
            f"static method '{receiver_type_name}.{method_name}' must be called on the class",
            span=callee.span,
        )

    return ResolvedCallTarget(
        name=method_label,
        receiver_expr=receiver_expr,
        return_type_name=ctx.method_return_types.get((receiver_type_name, method_name), "i64"),
    )


def resolve_call_target_name(
    callee: Expression,
    ctx: EmitContext,
) -> ResolvedCallTarget:
    if isinstance(callee, IdentifierExpr):
        ctor_label = ctx.constructor_labels.get(callee.name)
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None, return_type_name=callee.name)
        return ResolvedCallTarget(
            name=callee.name,
            receiver_expr=None,
            return_type_name=ctx.function_return_types.get(callee.name, RUNTIME_RETURN_TYPES.get(callee.name, "i64")),
        )

    if isinstance(callee, FieldAccessExpr):
        chain = _flatten_field_chain(callee)
        if chain is None:
            return _resolve_method_call_target(callee, ctx)
        if len(chain) < 2:
            codegen_types.raise_codegen_error(
                "call codegen currently supports direct or module-qualified callees only",
                span=callee.span,
            )
        if chain[0] in ctx.layout.slot_offsets:
            return _resolve_method_call_target(callee, ctx)
        static_owner = chain[-2]
        static_name = chain[-1]
        static_label = ctx.method_labels.get((static_owner, static_name))
        if static_label is not None and ctx.method_is_static.get((static_owner, static_name), False):
            return ResolvedCallTarget(
                name=static_label,
                receiver_expr=None,
                return_type_name=ctx.method_return_types.get((static_owner, static_name), "i64"),
            )
        ctor_label = ctx.constructor_labels.get(chain[-1])
        if ctor_label is not None:
            return ResolvedCallTarget(name=ctor_label, receiver_expr=None, return_type_name=chain[-1])
        return ResolvedCallTarget(
            name=chain[-1],
            receiver_expr=None,
            return_type_name=ctx.function_return_types.get(chain[-1], RUNTIME_RETURN_TYPES.get(chain[-1], "i64")),
        )

    codegen_types.raise_codegen_error(
        "call codegen currently supports direct or module-qualified callees only",
        span=getattr(callee, "span", None),
    )


def resolve_callable_value_label(
    expr: Expression,
    ctx: EmitContext,
) -> str | None:
    if isinstance(expr, IdentifierExpr):
        if expr.name in ctx.layout.slot_offsets:
            return None
        if expr.name in ctx.function_return_types:
            return expr.name
        return None

    if isinstance(expr, FieldAccessExpr):
        try:
            resolved_target = resolve_call_target_name(expr, ctx)
        except NotImplementedError:
            return None

        if resolved_target.receiver_expr is not None:
            return None
        if resolved_target.name in set(ctx.constructor_labels.values()):
            return None
        return resolved_target.name

    return None


def infer_expression_type_name(
    expr: Expression,
    ctx: EmitContext,
) -> str:
    if isinstance(expr, LiteralExpr):
        if expr.value.startswith('"'):
            return STR_CLASS_NAME
        if expr.value.startswith("'"):
            return "u8"
        if expr.value in {"true", "false"}:
            return "bool"
        if codegen_types.is_double_literal_text(expr.value):
            return "double"
        if expr.value.endswith("u8") and expr.value[:-2].isdigit():
            return "u8"
        if expr.value.endswith("u") and expr.value[:-1].isdigit():
            return "u64"
        return "i64"

    if isinstance(expr, NullExpr):
        return "null"

    if isinstance(expr, IdentifierExpr):
        return ctx.layout.slot_type_names.get(expr.name, "i64")

    if isinstance(expr, CastExpr):
        return codegen_types.type_ref_name(expr.type_ref)

    if isinstance(expr, ArrayCtorExpr):
        return codegen_types.type_ref_name(expr.element_type_ref)

    if isinstance(expr, FieldAccessExpr):
        receiver_type = field_receiver_type_name(expr.object_expr, ctx)
        if receiver_type is not None:
            receiver_candidates = [receiver_type]
            if "::" in receiver_type:
                receiver_candidates.append(receiver_type.split("::", 1)[1])

            for candidate in receiver_candidates:
                field_type_name = ctx.class_field_type_names.get((candidate, expr.field_name))
                if field_type_name is not None:
                    return field_type_name

            for (owner_type, field_name), field_type_name in ctx.class_field_type_names.items():
                if field_name != expr.field_name:
                    continue
                if owner_type == receiver_type or owner_type.endswith(f"::{receiver_type}"):
                    return field_type_name
        return "i64"

    if isinstance(expr, IndexExpr):
        receiver_type = infer_expression_type_name(expr.object_expr, ctx)
        if codegen_types.is_array_type_name(receiver_type):
            return codegen_types.array_element_type_name(receiver_type, span=expr.span)
        return "i64"

    if isinstance(expr, CallExpr):
        callee_type_name = infer_expression_type_name(expr.callee, ctx)
        if codegen_types.is_function_type_name(callee_type_name):
            return codegen_types.function_type_return_type_name(callee_type_name, span=expr.span)
        resolved_target = resolve_call_target_name(expr.callee, ctx)
        return resolved_target.return_type_name

    if isinstance(expr, UnaryExpr):
        if expr.operator == "!":
            return "bool"
        return infer_expression_type_name(expr.operand, ctx)

    if isinstance(expr, BinaryExpr):
        if expr.operator in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
            return "bool"
        return infer_expression_type_name(expr.left, ctx)

    return "i64"


def field_receiver_type_name(object_expr: Expression, ctx: EmitContext) -> str | None:
    if isinstance(object_expr, IdentifierExpr):
        return ctx.layout.slot_type_names.get(object_expr.name)
    if isinstance(object_expr, CastExpr):
        return codegen_types.type_ref_name(object_expr.type_ref)
    type_name = infer_expression_type_name(object_expr, ctx)
    if codegen_types.is_reference_type_name(type_name):
        return type_name
    return None