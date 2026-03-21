from __future__ import annotations

from collections.abc import Callable

from compiler.common.collection_protocols import CollectionOpKind
from compiler.frontend.ast_nodes import *
from compiler.semantic.ir import *
from compiler.typecheck.context import TypeCheckContext, declare_variable, pop_scope, push_scope
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.relations import canonicalize_reference_type_name
from compiler.typecheck.structural import resolve_for_in_element_type
from compiler.typecheck.type_resolution import resolve_type_ref

from compiler.semantic.lowering.collections import resolve_collection_dispatch, try_lower_slice_assign_stmt
from compiler.semantic.lowering.references import lower_lvalue


LowerExpr = Callable[[Expression], SemanticExpr]


def lower_function_like_body(
    typecheck_ctx: TypeCheckContext,
    *,
    params: list[ParamDecl],
    body: BlockStmt,
    receiver_type: TypeInfo | None,
    owner_class_name: str | None,
    lower_expr: LowerExpr,
) -> SemanticBlock:
    previous_owner = typecheck_ctx.current_private_owner_type
    if owner_class_name is not None:
        typecheck_ctx.current_private_owner_type = canonicalize_reference_type_name(typecheck_ctx, owner_class_name)

    push_scope(typecheck_ctx)
    typecheck_ctx.function_local_names_stack.append(set())
    try:
        if receiver_type is not None:
            declare_variable(typecheck_ctx, "__self", receiver_type, body.span)
        for param in params:
            declare_variable(typecheck_ctx, param.name, resolve_type_ref(typecheck_ctx, param.type_ref), param.span)
        return lower_block(typecheck_ctx, body, lower_expr=lower_expr)
    finally:
        typecheck_ctx.function_local_names_stack.pop()
        pop_scope(typecheck_ctx)
        typecheck_ctx.current_private_owner_type = previous_owner


def lower_block(typecheck_ctx: TypeCheckContext, block: BlockStmt, *, lower_expr: LowerExpr) -> SemanticBlock:
    push_scope(typecheck_ctx)
    try:
        return SemanticBlock(
            statements=[lower_stmt(typecheck_ctx, stmt, lower_expr=lower_expr) for stmt in block.statements],
            span=block.span,
        )
    finally:
        pop_scope(typecheck_ctx)


def lower_stmt(typecheck_ctx: TypeCheckContext, stmt: Statement, *, lower_expr: LowerExpr) -> SemanticStmt:
    if isinstance(stmt, BlockStmt):
        return lower_block(typecheck_ctx, stmt, lower_expr=lower_expr)

    if isinstance(stmt, VarDeclStmt):
        initializer = None if stmt.initializer is None else lower_expr(stmt.initializer)
        var_type = resolve_type_ref(typecheck_ctx, stmt.type_ref)
        declare_variable(typecheck_ctx, stmt.name, var_type, stmt.span)
        return SemanticVarDecl(name=stmt.name, type_name=var_type.name, initializer=initializer, span=stmt.span)

    if isinstance(stmt, IfStmt):
        return SemanticIf(
            condition=lower_expr(stmt.condition),
            then_block=lower_block(typecheck_ctx, stmt.then_branch, lower_expr=lower_expr),
            else_block=_lower_else_branch(typecheck_ctx, stmt.else_branch, lower_expr=lower_expr),
            span=stmt.span,
        )

    if isinstance(stmt, WhileStmt):
        return SemanticWhile(
            condition=lower_expr(stmt.condition),
            body=lower_block(typecheck_ctx, stmt.body, lower_expr=lower_expr),
            span=stmt.span,
        )

    if isinstance(stmt, ForInStmt):
        return _lower_for_in_stmt(typecheck_ctx, stmt, lower_expr=lower_expr)

    if isinstance(stmt, BreakStmt):
        return SemanticBreak(span=stmt.span)

    if isinstance(stmt, ContinueStmt):
        return SemanticContinue(span=stmt.span)

    if isinstance(stmt, ReturnStmt):
        value = None if stmt.value is None else lower_expr(stmt.value)
        return SemanticReturn(value=value, span=stmt.span)

    if isinstance(stmt, AssignStmt):
        return SemanticAssign(
            target=lower_lvalue(typecheck_ctx, stmt.target, lower_expr=lower_expr),
            value=lower_expr(stmt.value),
            span=stmt.span,
        )

    if isinstance(stmt, ExprStmt):
        slice_assign = try_lower_slice_assign_stmt(typecheck_ctx, stmt, lower_expr=lower_expr)
        if slice_assign is not None:
            return slice_assign
        return SemanticExprStmt(expr=lower_expr(stmt.expression), span=stmt.span)

    raise TypeError(f"Unsupported statement for semantic lowering: {type(stmt).__name__}")


def _lower_else_branch(
    typecheck_ctx: TypeCheckContext, else_branch: Statement | None, *, lower_expr: LowerExpr
) -> SemanticBlock | None:
    if isinstance(else_branch, BlockStmt):
        return lower_block(typecheck_ctx, else_branch, lower_expr=lower_expr)
    if isinstance(else_branch, IfStmt):
        nested_if = lower_stmt(typecheck_ctx, else_branch, lower_expr=lower_expr)
        return SemanticBlock(statements=[nested_if], span=else_branch.span)
    return None


def _lower_for_in_stmt(typecheck_ctx: TypeCheckContext, stmt: ForInStmt, *, lower_expr: LowerExpr) -> SemanticForIn:
    collection_type = infer_expression_type(typecheck_ctx, stmt.collection_expr)
    element_type = resolve_for_in_element_type(typecheck_ctx, collection_type, stmt.span)

    push_scope(typecheck_ctx)
    try:
        declare_variable(typecheck_ctx, stmt.element_name, element_type, stmt.span)
        body = lower_block(typecheck_ctx, stmt.body, lower_expr=lower_expr)
    finally:
        pop_scope(typecheck_ctx)

    return SemanticForIn(
        element_name=stmt.element_name,
        collection=lower_expr(stmt.collection_expr),
        iter_len_dispatch=resolve_collection_dispatch(
            typecheck_ctx, collection_type, operation=CollectionOpKind.ITER_LEN
        ),
        iter_get_dispatch=resolve_collection_dispatch(
            typecheck_ctx, collection_type, operation=CollectionOpKind.ITER_GET
        ),
        element_type_name=element_type.name,
        body=body,
        span=stmt.span,
    )
