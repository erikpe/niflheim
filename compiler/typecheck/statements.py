from __future__ import annotations

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_UNIT
from compiler.frontend.ast_nodes import *
from compiler.typecheck.context import TypeCheckContext, declare_variable, lookup_variable, pop_scope, push_scope
from compiler.typecheck.expressions import infer_expression_type
from compiler.common.span import SourceSpan
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.typecheck.relations import canonicalize_reference_type_name, require_assignable, require_type_name
from compiler.typecheck.structural import (
    ensure_index_assignment,
    ensure_structural_set_method_available_for_index_assignment,
    resolve_for_in_element_type,
)
from compiler.typecheck.type_resolution import resolve_type_ref
from compiler.typecheck.visibility import require_member_visible


def _ensure_field_access_assignable(ctx: TypeCheckContext, expr: FieldAccessExpr) -> None:
    object_type = infer_expression_type(ctx, expr.object_expr)
    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    field_type = class_info.fields.get(expr.field_name)
    if field_type is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    require_member_visible(ctx, class_info, object_type.name, expr.field_name, "field", expr.span)

    if expr.field_name in class_info.final_fields:
        raise TypeCheckError(f"Field '{class_info.name}.{expr.field_name}' is final", expr.span)


def _ensure_assignable_target(ctx: TypeCheckContext, expr: Expression) -> None:
    if isinstance(expr, IdentifierExpr):
        if lookup_variable(ctx, expr.name) is None:
            raise TypeCheckError("Invalid assignment target", expr.span)
        return

    if isinstance(expr, FieldAccessExpr):
        _ensure_field_access_assignable(ctx, expr)
        return

    if isinstance(expr, IndexExpr):
        object_type = infer_expression_type(ctx, expr.object_expr)
        if object_type.element_type is None:
            ensure_structural_set_method_available_for_index_assignment(ctx, object_type, expr.span)
        return

    raise TypeCheckError("Invalid assignment target", expr.span)


def _statement_guarantees_return(stmt: Statement, *, block_guarantees_return: callable) -> bool:
    if isinstance(stmt, ReturnStmt):
        return True

    if isinstance(stmt, BlockStmt):
        return block_guarantees_return(stmt)

    if isinstance(stmt, IfStmt):
        if stmt.else_branch is None:
            return False
        then_returns = block_guarantees_return(stmt.then_branch)
        else_returns = _statement_guarantees_return(stmt.else_branch, block_guarantees_return=block_guarantees_return)
        return then_returns and else_returns

    return False


def _block_guarantees_return(block: BlockStmt) -> bool:
    for stmt in block.statements:
        if _statement_guarantees_return(stmt, block_guarantees_return=_block_guarantees_return):
            return True
    return False


def _check_statement(ctx: TypeCheckContext, stmt: Statement, return_type: TypeInfo) -> None:
    if isinstance(stmt, BlockStmt):
        _check_block(ctx, stmt, return_type)
        return

    if isinstance(stmt, VarDeclStmt):
        var_type = resolve_type_ref(ctx, stmt.type_ref)
        if stmt.initializer is not None:
            init_type = infer_expression_type(ctx, stmt.initializer)
            require_assignable(ctx, var_type, init_type, stmt.initializer.span)
        declare_variable(ctx, stmt.name, var_type, stmt.span)
        return

    if isinstance(stmt, IfStmt):
        cond_type = infer_expression_type(ctx, stmt.condition)
        require_type_name(cond_type, TYPE_NAME_BOOL, stmt.condition.span)
        _check_block(ctx, stmt.then_branch, return_type)
        if isinstance(stmt.else_branch, BlockStmt):
            _check_block(ctx, stmt.else_branch, return_type)
        elif isinstance(stmt.else_branch, IfStmt):
            _check_statement(ctx, stmt.else_branch, return_type)
        return

    if isinstance(stmt, WhileStmt):
        cond_type = infer_expression_type(ctx, stmt.condition)
        require_type_name(cond_type, TYPE_NAME_BOOL, stmt.condition.span)
        ctx.loop_depth += 1
        _check_block(ctx, stmt.body, return_type)
        ctx.loop_depth -= 1
        return

    if isinstance(stmt, ForInStmt):
        collection_type = infer_expression_type(ctx, stmt.collection_expr)
        element_type = resolve_for_in_element_type(ctx, collection_type, stmt.span)
        object.__setattr__(stmt, "collection_type_name", collection_type.name)
        object.__setattr__(stmt, "element_type_name", element_type.name)

        ctx.loop_depth += 1
        push_scope(ctx)
        try:
            declare_variable(ctx, stmt.element_name, element_type, stmt.span)
            _check_block(ctx, stmt.body, return_type)
        finally:
            pop_scope(ctx)
            ctx.loop_depth -= 1
        return

    if isinstance(stmt, BreakStmt):
        if ctx.loop_depth <= 0:
            raise TypeCheckError("'break' is only allowed inside while loops", stmt.span)
        return

    if isinstance(stmt, ContinueStmt):
        if ctx.loop_depth <= 0:
            raise TypeCheckError("'continue' is only allowed inside while loops", stmt.span)
        return

    if isinstance(stmt, ReturnStmt):
        if stmt.value is None:
            if return_type.name != TYPE_NAME_UNIT:
                raise TypeCheckError("Non-unit function must return a value", stmt.span)
        else:
            value_type = infer_expression_type(ctx, stmt.value)
            require_assignable(ctx, return_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, AssignStmt):
        _ensure_assignable_target(ctx, stmt.target)
        if isinstance(stmt.target, IndexExpr):
            object_type = infer_expression_type(ctx, stmt.target.object_expr)
            value_type = infer_expression_type(ctx, stmt.value)
            ensure_index_assignment(ctx, object_type, stmt.target.index_expr, value_type, stmt.value.span)
            return

        target_type = infer_expression_type(ctx, stmt.target)
        value_type = infer_expression_type(ctx, stmt.value)
        require_assignable(ctx, target_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, ExprStmt):
        infer_expression_type(ctx, stmt.expression)


def _check_block(ctx: TypeCheckContext, block: BlockStmt, return_type: TypeInfo) -> None:
    push_scope(ctx)
    for stmt in block.statements:
        _check_statement(ctx, stmt, return_type)
    pop_scope(ctx)


def check_function_like(
    ctx: TypeCheckContext,
    params: list[ParamDecl],
    body: BlockStmt,
    return_type: TypeInfo,
    receiver_type: TypeInfo | None = None,
    owner_class_name: str | None = None,
) -> None:
    previous_owner = ctx.current_private_owner_type
    if owner_class_name is not None:
        ctx.current_private_owner_type = canonicalize_reference_type_name(ctx, owner_class_name)

    push_scope(ctx)
    try:
        if receiver_type is not None:
            declare_variable(ctx, "__self", receiver_type, body.span)
        for param in params:
            param_type = resolve_type_ref(ctx, param.type_ref)
            declare_variable(ctx, param.name, param_type, param.span)

        _check_block(ctx, body, return_type)

        if return_type.name != TYPE_NAME_UNIT and not _block_guarantees_return(body):
            raise TypeCheckError("Non-unit function must return on all paths", body.span)
    finally:
        pop_scope(ctx)
        ctx.current_private_owner_type = previous_owner
