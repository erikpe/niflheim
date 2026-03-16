from __future__ import annotations

from compiler.ast_nodes import BinaryExpr, CastExpr, Expression, LiteralExpr, NullExpr, UnaryExpr
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.relations import require_assignable
from compiler.typecheck.statements import check_function_like as statements_check_function_like


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


def check_class_field_initializers(ctx: TypeCheckContext) -> None:
    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        for field_decl in class_decl.fields:
            if field_decl.initializer is None:
                continue
            check_constant_field_initializer(field_decl.initializer)
            init_type = infer_expression_type(ctx, field_decl.initializer)
            field_type = class_info.fields[field_decl.name]
            require_assignable(ctx, field_type, init_type, field_decl.initializer.span)


def check_bodies(ctx: TypeCheckContext) -> None:
    check_class_field_initializers(ctx)

    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern:
            continue
        fn_sig = ctx.functions[fn_decl.name]
        body = fn_decl.body
        assert body is not None
        statements_check_function_like(ctx, fn_decl.params, body, fn_sig.return_type)

    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        for method_decl in class_decl.methods:
            method_sig = class_info.methods[method_decl.name]
            statements_check_function_like(
                ctx,
                method_decl.params,
                method_decl.body,
                method_sig.return_type,
                receiver_type=None if method_sig.is_static else TypeInfo(name=class_info.name, kind="reference"),
                owner_class_name=class_info.name,
            )
