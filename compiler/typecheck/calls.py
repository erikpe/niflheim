from __future__ import annotations

from compiler.ast_nodes import CallExpr, Expression, FieldAccessExpr, IdentifierExpr
from typing import TYPE_CHECKING

from compiler.lexer import SourceSpan
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import (
    lookup_class_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.relations import canonicalize_reference_type_name, require_assignable
from compiler.typecheck.structural import (
    infer_array_method_call_type,
    resolve_structural_set_slice_method_result_type,
    resolve_structural_slice_method_result_type,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner
from compiler.typecheck.visibility import require_member_visible

if TYPE_CHECKING:
    from compiler.typecheck.engine import TypeChecker


def callable_type_from_signature(name: str, signature: FunctionSig) -> TypeInfo:
    return TypeInfo(
        name=name,
        kind="callable",
        callable_params=signature.params,
        callable_return=signature.return_type,
    )


def class_type_name_from_callable(callable_name: str) -> str:
    if not callable_name.startswith("__class__:"):
        raise ValueError(f"invalid class callable name: {callable_name}")
    payload = callable_name[len("__class__:"):]
    if ":" not in payload:
        return payload
    owner_dotted, class_name = payload.rsplit(":", 1)
    return f"{owner_dotted}::{class_name}"


def check_call_arguments(
    checker: TypeChecker,
    params: list[TypeInfo],
    args: list[Expression],
    span: SourceSpan,
) -> None:
    ctx = checker.ctx

    if len(params) != len(args):
        raise TypeCheckError(f"Expected {len(params)} arguments, got {len(args)}", span)

    for param_type, arg_expr in zip(params, args):
        arg_type = infer_expression_type(checker, arg_expr)
        require_assignable(ctx, param_type, arg_type, arg_expr.span)


def infer_constructor_call_type(
    checker: TypeChecker,
    class_info: ClassInfo,
    args: list[Expression],
    span: SourceSpan,
    result_type: TypeInfo,
) -> TypeInfo:
    ctx = checker.ctx
    if class_info.constructor_is_private:
        owner_canonical = canonicalize_reference_type_name(ctx, result_type.name)
        if ctx.current_private_owner_type != owner_canonical:
            raise TypeCheckError(f"Constructor for class '{class_info.name}' is private", span)

    ctor_params = [class_info.fields[field_name] for field_name in class_info.constructor_param_order]
    check_call_arguments(checker, ctor_params, args, span)
    return result_type


def infer_call_type(
    checker: TypeChecker,
    expr: CallExpr,
) -> TypeInfo:
    ctx = checker.ctx

    if isinstance(expr.callee, IdentifierExpr):
        name = expr.callee.name

        fn_sig = ctx.functions.get(name)
        if fn_sig is not None:
            check_call_arguments(checker, fn_sig.params, expr.arguments, expr.span)
            return fn_sig.return_type

        imported_fn_sig = resolve_imported_function_sig(ctx, name, expr.callee.span)
        if imported_fn_sig is not None:
            check_call_arguments(checker, imported_fn_sig.params, expr.arguments, expr.span)
            return imported_fn_sig.return_type

        class_info = ctx.classes.get(name)
        if class_info is not None:
            return infer_constructor_call_type(
                checker,
                class_info,
                expr.arguments,
                expr.span,
                TypeInfo(name=class_info.name, kind="reference"),
            )

        imported_class_name = resolve_imported_class_name(ctx, name, expr.callee.span)
        if imported_class_name is not None:
            imported_class_info = lookup_class_by_type_name(ctx, imported_class_name)
            if imported_class_info is None:
                raise TypeCheckError(f"Unknown type '{imported_class_name}'", expr.callee.span)
            return infer_constructor_call_type(
                checker,
                imported_class_info,
                expr.arguments,
                expr.span,
                TypeInfo(name=imported_class_name, kind="reference"),
            )

    if isinstance(expr.callee, FieldAccessExpr):
        module_member = resolve_module_member(ctx, expr.callee)
        if module_member is not None:
            kind, owner_module, member_name = module_member
            if kind == "function":
                fn_sig = ctx.module_function_sigs[owner_module][member_name]
                check_call_arguments(checker, fn_sig.params, expr.arguments, expr.span)
                return fn_sig.return_type

            if kind == "class":
                class_info = ctx.module_class_infos[owner_module][member_name]
                owner_dotted = ".".join(owner_module)
                return infer_constructor_call_type(
                    checker,
                    class_info,
                    expr.arguments,
                    expr.span,
                    TypeInfo(name=f"{owner_dotted}::{class_info.name}", kind="reference"),
                )

            raise TypeCheckError("Module values are not callable", expr.callee.span)

        object_type = infer_expression_type(checker, expr.callee.object_expr)

        if object_type.kind == "callable" and object_type.name.startswith("__class__:"):
            class_type_name = class_type_name_from_callable(object_type.name)
            class_info = lookup_class_by_type_name(ctx, class_type_name)
            if class_info is None:
                raise TypeCheckError(f"Type '{class_type_name}' has no callable members", expr.span)

            method_sig = class_info.methods.get(expr.callee.field_name)
            if method_sig is None:
                raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
            require_member_visible(checker, class_info, class_type_name, expr.callee.field_name, "method", expr.span)
            if not method_sig.is_static:
                raise TypeCheckError(
                    f"Method '{class_info.name}.{expr.callee.field_name}' is not static",
                    expr.span,
                )

            qualified_params = [
                qualify_member_type_for_owner(ctx, param_type, class_type_name)
                for param_type in method_sig.params
            ]
            qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, class_type_name)

            check_call_arguments(checker, qualified_params, expr.arguments, expr.span)
            return qualified_return_type

        if object_type.element_type is not None:
            return infer_array_method_call_type(
                checker,
                object_type,
                expr.callee.field_name,
                expr.arguments,
                expr.span,
            )

        class_info = lookup_class_by_type_name(ctx, object_type.name)
        if class_info is None:
            raise TypeCheckError(f"Type '{object_type.name}' has no callable members", expr.span)

        method_sig = class_info.methods.get(expr.callee.field_name)
        if method_sig is None:
            field_type = class_info.fields.get(expr.callee.field_name)
            if field_type is not None:
                require_member_visible(checker, class_info, object_type.name,
                                       expr.callee.field_name, "field", expr.span)
                qualified_field_type = qualify_member_type_for_owner(ctx, field_type, object_type.name)
                if (
                    qualified_field_type.kind == "callable"
                    and qualified_field_type.callable_params is not None
                    and qualified_field_type.callable_return is not None
                ):
                    check_call_arguments(checker, qualified_field_type.callable_params, expr.arguments, expr.span)
                    return qualified_field_type.callable_return
                raise TypeCheckError(
                    f"Expression of type '{qualified_field_type.name}' is not callable",
                    expr.callee.span,
                )
            raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.callee.field_name}'", expr.span)
        require_member_visible(checker, class_info, object_type.name, expr.callee.field_name, "method", expr.span)

        if expr.callee.field_name == "slice_get":
            return resolve_structural_slice_method_result_type(
                checker,
                object_type,
                class_info,
                expr.arguments,
                expr.span,
            )

        if expr.callee.field_name == "slice_set":
            return resolve_structural_set_slice_method_result_type(
                checker,
                object_type,
                class_info,
                expr.arguments,
                expr.span,
            )

        if method_sig.is_static:
            raise TypeCheckError(
                f"Static method '{class_info.name}.{expr.callee.field_name}' must be called on the class",
                expr.span,
            )

        qualified_params = [
            qualify_member_type_for_owner(ctx, param_type, object_type.name)
            for param_type in method_sig.params
        ]
        qualified_return_type = qualify_member_type_for_owner(ctx, method_sig.return_type, object_type.name)

        check_call_arguments(checker, qualified_params, expr.arguments, expr.span)
        return qualified_return_type

    callee_type = infer_expression_type(checker, expr.callee)
    if callee_type.kind == "callable" and callee_type.callable_params is not None and callee_type.callable_return is not None:
        check_call_arguments(checker, callee_type.callable_params, expr.arguments, expr.span)
        return callee_type.callable_return
    raise TypeCheckError(f"Expression of type '{callee_type.name}' is not callable", expr.callee.span)
