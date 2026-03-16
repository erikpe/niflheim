from __future__ import annotations

from compiler.ast_nodes import CallExpr, Expression, FieldAccessExpr, IdentifierExpr

from compiler.typecheck.call_helpers import (
    callable_type_from_signature,
    check_call_argument_types,
    class_type_name_from_callable,
    infer_constructor_call_type as infer_constructor_call_type_from_types,
)
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.structural import infer_array_method_call_type, infer_structural_special_method_call_type
from compiler.typecheck.type_resolution import qualify_member_type_for_owner
from compiler.typecheck.visibility import require_member_visible


def check_call_arguments(ctx: TypeCheckContext, params: list[TypeInfo], args: list[Expression], span) -> None:
    check_call_argument_types(
        ctx,
        params,
        [infer_expression_type(ctx, arg_expr) for arg_expr in args],
        [arg_expr.span for arg_expr in args],
        span,
    )


def infer_constructor_call_type(
    ctx: TypeCheckContext, class_info, args: list[Expression], span, result_type: TypeInfo
) -> TypeInfo:
    return infer_constructor_call_type_from_types(
        ctx,
        class_info,
        [infer_expression_type(ctx, arg_expr) for arg_expr in args],
        [arg_expr.span for arg_expr in args],
        span,
        result_type,
    )


def infer_identifier_call_type(ctx: TypeCheckContext, expr: CallExpr) -> TypeInfo | None:
    if not isinstance(expr.callee, IdentifierExpr):
        return None

    name = expr.callee.name

    fn_sig = ctx.functions.get(name)
    if fn_sig is not None:
        check_call_arguments(ctx, fn_sig.params, expr.arguments, expr.span)
        return fn_sig.return_type

    imported_fn_sig = resolve_imported_function_sig(ctx, name, expr.callee.span)
    if imported_fn_sig is not None:
        check_call_arguments(ctx, imported_fn_sig.params, expr.arguments, expr.span)
        return imported_fn_sig.return_type

    class_info = ctx.classes.get(name)
    if class_info is not None:
        return infer_constructor_call_type(
            ctx, class_info, expr.arguments, expr.span, TypeInfo(name=class_info.name, kind="reference")
        )

    imported_class_name = resolve_imported_class_name(ctx, name, expr.callee.span)
    if imported_class_name is None:
        return None

    imported_class_info = lookup_class_by_type_name(ctx, imported_class_name)
    if imported_class_info is None:
        raise TypeCheckError(f"Unknown type '{imported_class_name}'", expr.callee.span)
    return infer_constructor_call_type(
        ctx, imported_class_info, expr.arguments, expr.span, TypeInfo(name=imported_class_name, kind="reference")
    )


def infer_module_member_call_type(ctx: TypeCheckContext, expr: CallExpr) -> TypeInfo | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    module_member = resolve_module_member(ctx, expr.callee)
    if module_member is None:
        return None

    kind, owner_module, member_name = module_member
    if kind == "function":
        fn_sig = ctx.module_function_sigs[owner_module][member_name]
        check_call_arguments(ctx, fn_sig.params, expr.arguments, expr.span)
        return fn_sig.return_type

    if kind == "class":
        class_info = ctx.module_class_infos[owner_module][member_name]
        owner_dotted = ".".join(owner_module)
        return infer_constructor_call_type(
            ctx,
            class_info,
            expr.arguments,
            expr.span,
            TypeInfo(name=f"{owner_dotted}::{class_info.name}", kind="reference"),
        )

    raise TypeCheckError("Module values are not callable", expr.callee.span)


def infer_class_callable_method_call_type(ctx: TypeCheckContext, expr: CallExpr, class_type_name: str) -> TypeInfo:
    class_info = lookup_class_by_type_name(ctx, class_type_name)
    if class_info is None:
        raise TypeCheckError(f"Type '{class_type_name}' has no callable members", expr.span)

    method_sig = class_info.methods.get(expr.callee.field_name)
    if method_sig is None:
        raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
    require_member_visible(ctx, class_info, class_type_name, expr.callee.field_name, "method", expr.span)
    if not method_sig.is_static:
        raise TypeCheckError(f"Method '{class_info.name}.{expr.callee.field_name}' is not static", expr.span)

    qualified_params = [
        qualify_member_type_for_owner(ctx, param_type, class_type_name) for param_type in method_sig.params
    ]
    qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, class_type_name)
    check_call_arguments(ctx, qualified_params, expr.arguments, expr.span)
    return qualified_return_type


def infer_instance_field_call_type(
    ctx: TypeCheckContext, expr: CallExpr, object_type: TypeInfo, class_info
) -> TypeInfo | None:
    field_type = class_info.fields.get(expr.callee.field_name)
    if field_type is None:
        return None

    require_member_visible(ctx, class_info, object_type.name, expr.callee.field_name, "field", expr.span)
    qualified_field_type = qualify_member_type_for_owner(ctx, field_type, object_type.name)
    if (
        qualified_field_type.kind == "callable"
        and qualified_field_type.callable_params is not None
        and qualified_field_type.callable_return is not None
    ):
        check_call_arguments(ctx, qualified_field_type.callable_params, expr.arguments, expr.span)
        return qualified_field_type.callable_return

    raise TypeCheckError(f"Expression of type '{qualified_field_type.name}' is not callable", expr.callee.span)


def infer_instance_method_call_type(
    ctx: TypeCheckContext, expr: CallExpr, object_type: TypeInfo, class_info
) -> TypeInfo:
    method_sig = class_info.methods.get(expr.callee.field_name)
    if method_sig is None:
        field_result = infer_instance_field_call_type(ctx, expr, object_type, class_info)
        if field_result is not None:
            return field_result
        raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)

    require_member_visible(ctx, class_info, object_type.name, expr.callee.field_name, "method", expr.span)

    structural_result = infer_structural_special_method_call_type(
        ctx, object_type, class_info, expr.callee.field_name, expr.arguments, expr.span
    )
    if structural_result is not None:
        return structural_result

    if method_sig.is_static:
        raise TypeCheckError(
            f"Static method '{class_info.name}.{expr.callee.field_name}' must be called on the class", expr.span
        )

    qualified_params = [
        qualify_member_type_for_owner(ctx, param_type, object_type.name) for param_type in method_sig.params
    ]
    qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)
    check_call_arguments(ctx, qualified_params, expr.arguments, expr.span)
    return qualified_return_type


def infer_field_access_call_type(ctx: TypeCheckContext, expr: CallExpr) -> TypeInfo | None:
    if not isinstance(expr.callee, FieldAccessExpr):
        return None

    module_member_result = infer_module_member_call_type(ctx, expr)
    if module_member_result is not None:
        return module_member_result

    object_type = infer_expression_type(ctx, expr.callee.object_expr)

    if object_type.kind == "callable" and object_type.name.startswith("__class__:"):
        return infer_class_callable_method_call_type(ctx, expr, class_type_name_from_callable(object_type.name))

    if object_type.element_type is not None:
        return infer_array_method_call_type(ctx, object_type, expr.callee.field_name, expr.arguments, expr.span)

    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is None:
        raise TypeCheckError(f"Type '{object_type.name}' has no callable members", expr.span)

    return infer_instance_method_call_type(ctx, expr, object_type, class_info)


def infer_callable_value_call_type(ctx: TypeCheckContext, expr: CallExpr) -> TypeInfo:
    callee_type = infer_expression_type(ctx, expr.callee)
    if (
        callee_type.kind == "callable"
        and callee_type.callable_params is not None
        and callee_type.callable_return is not None
    ):
        check_call_arguments(ctx, callee_type.callable_params, expr.arguments, expr.span)
        return callee_type.callable_return
    raise TypeCheckError(f"Expression of type '{callee_type.name}' is not callable", expr.callee.span)


def infer_call_type(ctx: TypeCheckContext, expr: CallExpr) -> TypeInfo:
    identifier_result = infer_identifier_call_type(ctx, expr)
    if identifier_result is not None:
        return identifier_result

    field_access_result = infer_field_access_call_type(ctx, expr)
    if field_access_result is not None:
        return field_access_result

    return infer_callable_value_call_type(ctx, expr)
