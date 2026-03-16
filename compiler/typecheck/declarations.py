from __future__ import annotations

from compiler.ast_nodes import (
    BinaryExpr,
    CastExpr,
    Expression,
    FunctionDecl,
    MethodDecl,
    NullExpr,
    UnaryExpr,
    LiteralExpr,
)
from typing import TYPE_CHECKING

from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeCheckError, TypeInfo
from compiler.typecheck.relations import require_assignable
from compiler.typecheck.type_resolution import resolve_type_ref

if TYPE_CHECKING:
    from compiler.typecheck.engine import TypeChecker


def check_constant_field_initializer(expr: Expression) -> None:
    if isinstance(expr, (LiteralExpr, NullExpr)):
        return
    if isinstance(expr, UnaryExpr):
        check_constant_field_initializer(expr.operand)
        return
    if isinstance(expr, BinaryExpr):
        check_constant_field_initializer(expr.left)
        check_constant_field_initializer(expr.right)
        return
    if isinstance(expr, CastExpr):
        check_constant_field_initializer(expr.operand)
        return
    raise TypeCheckError(
        "Class field initializer must be a constant expression in MVP",
        expr.span,
    )


def function_sig_from_decl(
    ctx: TypeCheckContext,
    decl: FunctionDecl | MethodDecl,
) -> FunctionSig:
    params = [
        resolve_type_ref(
            ctx,
            param.type_ref,
        )
        for param in decl.params
    ]
    return FunctionSig(
        name=decl.name,
        params=params,
        return_type=resolve_type_ref(
            ctx,
            decl.return_type,
        ),
        is_static=decl.is_static if isinstance(decl, MethodDecl) else False,
        is_private=decl.is_private if isinstance(decl, MethodDecl) else False,
    )


def collect_module_declarations(
    checker: TypeChecker,
) -> None:
    ctx = checker.ctx

    for class_decl in ctx.module_ast.classes:
        if class_decl.name in ctx.classes or class_decl.name in ctx.functions:
            raise TypeCheckError(f"Duplicate declaration '{class_decl.name}'", class_decl.span)
        ctx.classes[class_decl.name] = ClassInfo(
            name=class_decl.name,
            fields={},
            field_order=[],
            constructor_param_order=[],
            methods={},
            private_fields=set(),
            final_fields=set(),
            private_methods=set(),
            constructor_is_private=False,
        )

    for class_decl in ctx.module_ast.classes:
        fields: dict[str, TypeInfo] = {}
        field_order: list[str] = []
        constructor_param_order: list[str] = []
        for field_decl in class_decl.fields:
            if field_decl.name in fields:
                raise TypeCheckError(f"Duplicate field '{field_decl.name}'", field_decl.span)
            field_type = resolve_type_ref(
                ctx,
                field_decl.type_ref,
            )
            if field_decl.initializer is not None:
                check_constant_field_initializer(field_decl.initializer)
                init_type = infer_expression_type(checker, field_decl.initializer)
                require_assignable(ctx, field_type, init_type, field_decl.initializer.span)
            else:
                constructor_param_order.append(field_decl.name)
            fields[field_decl.name] = field_type
            field_order.append(field_decl.name)

        methods: dict[str, FunctionSig] = {}
        for method_decl in class_decl.methods:
            if method_decl.name in methods:
                raise TypeCheckError(f"Duplicate method '{method_decl.name}'", method_decl.span)
            if method_decl.name in fields:
                raise TypeCheckError(f"Duplicate member '{method_decl.name}'", method_decl.span)
            methods[method_decl.name] = function_sig_from_decl(
                ctx,
                method_decl,
            )

        private_fields = {field_decl.name for field_decl in class_decl.fields if field_decl.is_private}
        final_fields = {field_decl.name for field_decl in class_decl.fields if field_decl.is_final}
        private_methods = {method_decl.name for method_decl in class_decl.methods if method_decl.is_private}

        ctx.classes[class_decl.name] = ClassInfo(
            name=class_decl.name,
            fields=fields,
            field_order=field_order,
            constructor_param_order=constructor_param_order,
            methods=methods,
            private_fields=private_fields,
            final_fields=final_fields,
            private_methods=private_methods,
            constructor_is_private=len(private_fields) > 0,
        )

    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern and fn_decl.body is not None:
            raise TypeCheckError("Extern function must not have a body", fn_decl.span)
        if not fn_decl.is_extern and fn_decl.body is None:
            raise TypeCheckError("Function declaration missing body", fn_decl.span)
        if fn_decl.name in ctx.functions or fn_decl.name in ctx.classes:
            raise TypeCheckError(f"Duplicate declaration '{fn_decl.name}'", fn_decl.span)
        ctx.functions[fn_decl.name] = function_sig_from_decl(
            ctx,
            fn_decl,
        )
