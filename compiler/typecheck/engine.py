from __future__ import annotations

from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.statements import check_function_like as statements_check_function_like


def check_bodies(ctx: TypeCheckContext) -> None:
    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern:
            continue
        fn_sig = ctx.functions[fn_decl.name]
        if fn_decl.body is None:
            raise TypeCheckError("Function declaration missing body", fn_decl.span)
        statements_check_function_like(ctx, fn_decl.params, fn_decl.body, fn_sig.return_type)

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
