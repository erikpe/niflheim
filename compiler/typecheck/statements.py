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
from compiler.typecheck.context import TypeCheckContext
from compiler.lexer import SourceSpan
from compiler.typecheck.model import ClassInfo, TypeCheckError, TypeInfo
from compiler.typecheck.ops import TypeCheckOps


def require_member_visible(
    ctx: TypeCheckContext,
    ops: TypeCheckOps,
    class_info: ClassInfo,
    owner_type_name: str,
    member_name: str,
    member_kind: str,
    span: SourceSpan,
) -> None:
    is_private = (
        member_name in class_info.private_fields
        if member_kind == "field"
        else member_name in class_info.private_methods
    )
    if not is_private:
        return

    owner_canonical = ops.canonicalize_reference_type_name(owner_type_name)
    if ctx.current_private_owner_type == owner_canonical:
        return

    raise TypeCheckError(f"Member '{class_info.name}.{member_name}' is private", span)


def ensure_field_access_assignable(
    ops: TypeCheckOps,
    expr: FieldAccessExpr,
) -> None:
    object_type = ops.infer_expression_type(expr.object_expr)
    class_info = ops.lookup_class_by_type_name(object_type.name)
    if class_info is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    field_type = class_info.fields.get(expr.field_name)
    if field_type is None:
        raise TypeCheckError("Invalid assignment target", expr.span)

    ops.require_member_visible(class_info, object_type.name, expr.field_name, "field", expr.span)

    if expr.field_name in class_info.final_fields:
        raise TypeCheckError(f"Field '{class_info.name}.{expr.field_name}' is final", expr.span)


def ensure_assignable_target(
    ops: TypeCheckOps,
    expr: Expression,
) -> None:
    if isinstance(expr, IdentifierExpr):
        if ops.lookup_variable(expr.name) is None:
            raise TypeCheckError("Invalid assignment target", expr.span)
        return

    if isinstance(expr, FieldAccessExpr):
        ensure_field_access_assignable(ops, expr)
        return

    if isinstance(expr, IndexExpr):
        object_type = ops.infer_expression_type(expr.object_expr)
        if object_type.element_type is None:
            ops.ensure_structural_set_method_available_for_index_assignment(object_type, expr.span)
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
    ctx: TypeCheckContext,
    ops: TypeCheckOps,
    stmt: Statement,
    return_type: TypeInfo,
) -> None:
    if isinstance(stmt, BlockStmt):
        check_block(ops, stmt, return_type)
        return

    if isinstance(stmt, VarDeclStmt):
        var_type = ops.resolve_type_ref(stmt.type_ref)
        if stmt.initializer is not None:
            init_type = ops.infer_expression_type(stmt.initializer)
            ops.require_assignable(var_type, init_type, stmt.initializer.span)
        ops.declare_variable(stmt.name, var_type, stmt.span)
        return

    if isinstance(stmt, IfStmt):
        cond_type = ops.infer_expression_type(stmt.condition)
        ops.require_type_name(cond_type, "bool", stmt.condition.span)
        check_block(ops, stmt.then_branch, return_type)
        if isinstance(stmt.else_branch, BlockStmt):
            check_block(ops, stmt.else_branch, return_type)
        elif isinstance(stmt.else_branch, IfStmt):
            check_statement(ctx, ops, stmt.else_branch, return_type)
        return

    if isinstance(stmt, WhileStmt):
        cond_type = ops.infer_expression_type(stmt.condition)
        ops.require_type_name(cond_type, "bool", stmt.condition.span)
        ctx.loop_depth += 1
        check_block(ops, stmt.body, return_type)
        ctx.loop_depth -= 1
        return

    if isinstance(stmt, ForInStmt):
        collection_type = ops.infer_expression_type(stmt.collection_expr)
        element_type = ops.resolve_for_in_element_type(collection_type, stmt.span)
        object.__setattr__(stmt, "collection_type_name", collection_type.name)
        object.__setattr__(stmt, "element_type_name", element_type.name)

        ctx.loop_depth += 1
        ops.push_scope()
        try:
            ops.declare_variable(stmt.element_name, element_type, stmt.span)
            check_block(ops, stmt.body, return_type)
        finally:
            ops.pop_scope()
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
            value_type = ops.infer_expression_type(stmt.value)
            ops.require_assignable(return_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, AssignStmt):
        ensure_assignable_target(ops, stmt.target)
        if isinstance(stmt.target, IndexExpr):
            object_type = ops.infer_expression_type(stmt.target.object_expr)
            value_type = ops.infer_expression_type(stmt.value)
            ops.ensure_index_assignment(object_type, stmt.target.index_expr, value_type, stmt.value.span)
            return

        target_type = ops.infer_expression_type(stmt.target)
        value_type = ops.infer_expression_type(stmt.value)
        ops.require_assignable(target_type, value_type, stmt.value.span)
        return

    if isinstance(stmt, ExprStmt):
        ops.infer_expression_type(stmt.expression)


def check_block(ops: TypeCheckOps, block: BlockStmt, return_type: TypeInfo) -> None:
    ops.push_scope()
    for stmt in block.statements:
        ops.check_statement(stmt, return_type)
    ops.pop_scope()


def check_function_like(
    ctx: TypeCheckContext,
    ops: TypeCheckOps,
    params: list[ParamDecl],
    body: BlockStmt,
    return_type: TypeInfo,
    receiver_type: TypeInfo | None = None,
    owner_class_name: str | None = None,
) -> None:
    previous_owner = ctx.current_private_owner_type
    if owner_class_name is not None:
        ctx.current_private_owner_type = ops.canonicalize_reference_type_name(owner_class_name)

    ops.push_scope()
    ctx.function_local_names_stack.append(set())
    try:
        if receiver_type is not None:
            ops.declare_variable("__self", receiver_type, body.span)
        for param in params:
            param_type = ops.resolve_type_ref(param.type_ref)
            ops.declare_variable(param.name, param_type, param.span)

        check_block(ops, body, return_type)

        if return_type.name != "unit" and not ops.block_guarantees_return(body):
            raise TypeCheckError("Non-unit function must return on all paths", body.span)
    finally:
        ctx.function_local_names_stack.pop()
        ops.pop_scope()
        ctx.current_private_owner_type = previous_owner
