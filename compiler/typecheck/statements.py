from __future__ import annotations

from compiler.ast_nodes import (
    AssignStmt,
    BlockStmt,
    BreakStmt,
    ContinueStmt,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForInStmt,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    ParamDecl,
    ReturnStmt,
    Statement,
    VarDeclStmt,
    WhileStmt,
)
from typing import TYPE_CHECKING

from compiler.typecheck.context import TypeCheckContext, declare_variable, lookup_variable, pop_scope, push_scope
from compiler.lexer import SourceSpan
from compiler.typecheck.model import ClassInfo, TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.typecheck.relations import canonicalize_reference_type_name, require_assignable, require_type_name
from compiler.typecheck.type_resolution import resolve_type_ref

if TYPE_CHECKING:
    from compiler.typecheck.engine import TypeChecker


def require_member_visible(
    checker: TypeChecker,
    class_info: ClassInfo,
    owner_type_name: str,
    member_name: str,
    member_kind: str,
    span: SourceSpan,
) -> None:
    ctx = checker.ctx
    is_private = (
        member_name in class_info.private_fields
        if member_kind == "field"
        else member_name in class_info.private_methods
    )
    if not is_private:
        return

    owner_canonical = canonicalize_reference_type_name(ctx, owner_type_name)
    if ctx.current_private_owner_type == owner_canonical:
        return

    raise TypeCheckError(f"Member '{class_info.name}.{member_name}' is private", span)


def ensure_field_access_assignable(
    checker: TypeChecker,
    expr: FieldAccessExpr,
) -> None:
    object_type = checker.infer_expression_type(expr.object_expr)
    class_info = lookup_class_by_type_name(checker.ctx, object_type.name)
    if class_info is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    field_type = class_info.fields.get(expr.field_name)
    if field_type is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    require_member_visible(checker, class_info, object_type.name, expr.field_name, "field", expr.span)

    if expr.field_name in class_info.final_fields:
        raise TypeCheckError(f"Field '{class_info.name}.{expr.field_name}' is final", expr.span)


def ensure_assignable_target(
    checker: TypeChecker,
    expr: Expression,
) -> None:
    if isinstance(expr, IdentifierExpr):
        if lookup_variable(checker.ctx, expr.name) is None:
            raise TypeCheckError("Invalid assignment target", expr.span)
        return

    if isinstance(expr, FieldAccessExpr):
        ensure_field_access_assignable(checker, expr)
        return

    if isinstance(expr, IndexExpr):
        object_type = checker.infer_expression_type(expr.object_expr)
        if object_type.element_type is None:
            checker.ensure_structural_set_method_available_for_index_assignment(object_type, expr.span)
        return

    raise TypeCheckError("Invalid assignment target", expr.span)


def statement_guarantees_return(stmt: Statement, *, block_guarantees_return: callable) -> bool:
    if isinstance(stmt, ReturnStmt):
        return True

    if isinstance(stmt, BlockStmt):
        return block_guarantees_return(stmt)

    if isinstance(stmt, IfStmt):
        if stmt.else_branch is None:
            return False
        then_returns = block_guarantees_return(stmt.then_branch)
        else_returns = statement_guarantees_return(stmt.else_branch, block_guarantees_return=block_guarantees_return)
        return then_returns and else_returns

    return False


def block_guarantees_return(block: BlockStmt) -> bool:
    for stmt in block.statements:
        if statement_guarantees_return(stmt, block_guarantees_return=block_guarantees_return):
            return True
    return False


def check_statement(
    checker: TypeChecker,
    stmt: Statement,
    return_type: TypeInfo,
) -> None:
    ctx = checker.ctx
    if isinstance(stmt, BlockStmt):
        check_block(checker, stmt, return_type)
        return

    if isinstance(stmt, VarDeclStmt):
        var_type = resolve_type_ref(ctx, stmt.type_ref)
        if stmt.initializer is not None:
            init_type = checker.infer_expression_type(stmt.initializer)
            require_assignable(ctx, var_type, init_type, stmt.initializer.span)
        declare_variable(ctx, stmt.name, var_type, stmt.span)
        return

    if isinstance(stmt, IfStmt):
        cond_type = checker.infer_expression_type(stmt.condition)
        require_type_name(cond_type, "bool", stmt.condition.span)
        check_block(checker, stmt.then_branch, return_type)
        if isinstance(stmt.else_branch, BlockStmt):
            check_block(checker, stmt.else_branch, return_type)
        elif isinstance(stmt.else_branch, IfStmt):
            check_statement(checker, stmt.else_branch, return_type)
        return

    if isinstance(stmt, WhileStmt):
        cond_type = checker.infer_expression_type(stmt.condition)
        require_type_name(cond_type, "bool", stmt.condition.span)
        ctx.loop_depth += 1
        check_block(checker, stmt.body, return_type)
        ctx.loop_depth -= 1
        return

    if isinstance(stmt, ForInStmt):
        collection_type = checker.infer_expression_type(stmt.collection_expr)
        element_type = checker.resolve_for_in_element_type(collection_type, stmt.span)
        object.__setattr__(stmt, "collection_type_name", collection_type.name)
        object.__setattr__(stmt, "element_type_name", element_type.name)

        ctx.loop_depth += 1
        push_scope(ctx)
        try:
            declare_variable(ctx, stmt.element_name, element_type, stmt.span)
            check_block(checker, stmt.body, return_type)
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
            if return_type.name != "unit":
                raise TypeCheckError("Non-unit function must return a value", stmt.span)
        else:
            value_type = checker.infer_expression_type(stmt.value)
            require_assignable(ctx, return_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, AssignStmt):
        ensure_assignable_target(checker, stmt.target)
        if isinstance(stmt.target, IndexExpr):
            object_type = checker.infer_expression_type(stmt.target.object_expr)
            value_type = checker.infer_expression_type(stmt.value)
            checker.ensure_index_assignment(object_type, stmt.target.index_expr, value_type, stmt.value.span)
            return

        target_type = checker.infer_expression_type(stmt.target)
        value_type = checker.infer_expression_type(stmt.value)
        require_assignable(ctx, target_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, ExprStmt):
        checker.infer_expression_type(stmt.expression)


def check_block(checker: TypeChecker, block: BlockStmt, return_type: TypeInfo) -> None:
    push_scope(checker.ctx)
    for stmt in block.statements:
        check_statement(checker, stmt, return_type)
    pop_scope(checker.ctx)


def check_function_like(
    checker: TypeChecker,
    params: list[ParamDecl],
    body: BlockStmt,
    return_type: TypeInfo,
    receiver_type: TypeInfo | None = None,
    owner_class_name: str | None = None,
) -> None:
    ctx = checker.ctx
    previous_owner = ctx.current_private_owner_type
    if owner_class_name is not None:
        ctx.current_private_owner_type = canonicalize_reference_type_name(ctx, owner_class_name)

    push_scope(ctx)
    ctx.function_local_names_stack.append(set())
    try:
        if receiver_type is not None:
            declare_variable(ctx, "__self", receiver_type, body.span)
        for param in params:
            param_type = resolve_type_ref(ctx, param.type_ref)
            declare_variable(ctx, param.name, param_type, param.span)

        check_block(checker, body, return_type)

        if return_type.name != "unit" and not block_guarantees_return(body):
            raise TypeCheckError("Non-unit function must return on all paths", body.span)
    finally:
        ctx.function_local_names_stack.pop()
        pop_scope(ctx)
        ctx.current_private_owner_type = previous_owner
