from __future__ import annotations

from dataclasses import dataclass

from compiler.common.collection_protocols import CollectionOpKind
from compiler.frontend.ast_nodes import *
from compiler.semantic.ir import *
from compiler.semantic.lowering.expressions import lower_expr
from compiler.semantic.lowering.locals import LocalIdTracker
from compiler.typecheck.context import TypeCheckContext, declare_variable, pop_scope, push_scope
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.relations import canonicalize_reference_type_name
from compiler.typecheck.structural import resolve_for_in_element_type
from compiler.typecheck.type_resolution import resolve_type_ref

from compiler.semantic.lowering.collections import resolve_collection_dispatch, try_lower_slice_assign_stmt
from compiler.semantic.lowering.references import lower_lvalue
from compiler.semantic.symbols import FunctionId, MethodId


@dataclass(frozen=True)
class LoweredFunctionBody:
    body: SemanticBlock
    local_info_by_id: dict[LocalId, SemanticLocalInfo]


def lower_function_like_body(
    typecheck_ctx: TypeCheckContext,
    *,
    owner_id: FunctionId | MethodId,
    symbol_index,
    params: list[ParamDecl],
    body: BlockStmt,
    receiver_type: TypeInfo | None,
    owner_class_name: str | None,
) -> LoweredFunctionBody:
    previous_owner = typecheck_ctx.current_private_owner_type
    if owner_class_name is not None:
        typecheck_ctx.current_private_owner_type = canonicalize_reference_type_name(typecheck_ctx, owner_class_name)

    local_id_tracker = LocalIdTracker(owner_id=owner_id)
    push_scope(typecheck_ctx)
    local_id_tracker.push_scope()
    typecheck_ctx.function_local_names_stack.append(set())
    try:
        if receiver_type is not None:
            declare_variable(typecheck_ctx, "__self", receiver_type, body.span)
            local_id_tracker.declare_local(
                "__self",
                type_name=receiver_type.name,
                span=body.span,
                binding_kind="receiver",
            )
        for param in params:
            param_type = resolve_type_ref(typecheck_ctx, param.type_ref)
            declare_variable(typecheck_ctx, param.name, param_type, param.span)
            local_id_tracker.declare_local(
                param.name,
                type_name=param_type.name,
                span=param.span,
                binding_kind="param",
            )
        lowered_body = lower_block(typecheck_ctx, body, symbol_index=symbol_index, local_id_tracker=local_id_tracker)
        return LoweredFunctionBody(
            body=lowered_body,
            local_info_by_id=local_id_tracker.snapshot_local_info_by_id(),
        )
    finally:
        typecheck_ctx.function_local_names_stack.pop()
        local_id_tracker.pop_scope()
        pop_scope(typecheck_ctx)
        typecheck_ctx.current_private_owner_type = previous_owner


def lower_block(
    typecheck_ctx: TypeCheckContext,
    block: BlockStmt,
    *,
    symbol_index,
    local_id_tracker: LocalIdTracker,
) -> SemanticBlock:
    push_scope(typecheck_ctx)
    local_id_tracker.push_scope()
    try:
        return SemanticBlock(
            statements=[
                lower_stmt(typecheck_ctx, stmt, symbol_index=symbol_index, local_id_tracker=local_id_tracker)
                for stmt in block.statements
            ],
            span=block.span,
        )
    finally:
        local_id_tracker.pop_scope()
        pop_scope(typecheck_ctx)


def lower_stmt(typecheck_ctx: TypeCheckContext, stmt: Statement, *, symbol_index, local_id_tracker: LocalIdTracker) -> SemanticStmt:
    if isinstance(stmt, BlockStmt):
        return lower_block(typecheck_ctx, stmt, symbol_index=symbol_index, local_id_tracker=local_id_tracker)

    if isinstance(stmt, VarDeclStmt):
        initializer = (
            None if stmt.initializer is None else lower_expr(typecheck_ctx, symbol_index, stmt.initializer, local_id_tracker)
        )
        var_type = resolve_type_ref(typecheck_ctx, stmt.type_ref)
        declare_variable(typecheck_ctx, stmt.name, var_type, stmt.span)
        local_id = local_id_tracker.declare_local(stmt.name, type_name=var_type.name, span=stmt.span)
        return SemanticVarDecl(
            local_id=local_id,
            name=stmt.name,
            type_name=var_type.name,
            initializer=initializer,
            span=stmt.span,
        )

    if isinstance(stmt, IfStmt):
        return SemanticIf(
            condition=lower_expr(typecheck_ctx, symbol_index, stmt.condition, local_id_tracker),
            then_block=lower_block(
                typecheck_ctx, stmt.then_branch, symbol_index=symbol_index, local_id_tracker=local_id_tracker
            ),
            else_block=_lower_else_branch(
                typecheck_ctx, stmt.else_branch, symbol_index=symbol_index, local_id_tracker=local_id_tracker
            ),
            span=stmt.span,
        )

    if isinstance(stmt, WhileStmt):
        return SemanticWhile(
            condition=lower_expr(typecheck_ctx, symbol_index, stmt.condition, local_id_tracker),
            body=lower_block(typecheck_ctx, stmt.body, symbol_index=symbol_index, local_id_tracker=local_id_tracker),
            span=stmt.span,
        )

    if isinstance(stmt, ForInStmt):
        return _lower_for_in_stmt(typecheck_ctx, stmt, symbol_index=symbol_index, local_id_tracker=local_id_tracker)

    if isinstance(stmt, BreakStmt):
        return SemanticBreak(span=stmt.span)

    if isinstance(stmt, ContinueStmt):
        return SemanticContinue(span=stmt.span)

    if isinstance(stmt, ReturnStmt):
        value = None if stmt.value is None else lower_expr(typecheck_ctx, symbol_index, stmt.value, local_id_tracker)
        return SemanticReturn(value=value, span=stmt.span)

    if isinstance(stmt, AssignStmt):
        return SemanticAssign(
            target=lower_lvalue(
                typecheck_ctx,
                stmt.target,
                lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
                local_id_tracker=local_id_tracker,
            ),
            value=lower_expr(typecheck_ctx, symbol_index, stmt.value, local_id_tracker),
            span=stmt.span,
        )

    if isinstance(stmt, ExprStmt):
        slice_assign = try_lower_slice_assign_stmt(
            typecheck_ctx,
            stmt,
            lower_expr=lambda nested_expr: lower_expr(typecheck_ctx, symbol_index, nested_expr, local_id_tracker),
        )
        if slice_assign is not None:
            return slice_assign
        return SemanticExprStmt(
            expr=lower_expr(typecheck_ctx, symbol_index, stmt.expression, local_id_tracker), span=stmt.span
        )

    raise TypeError(f"Unsupported statement for semantic lowering: {type(stmt).__name__}")


def _lower_else_branch(
    typecheck_ctx: TypeCheckContext,
    else_branch: Statement | None,
    *,
    symbol_index,
    local_id_tracker: LocalIdTracker,
) -> SemanticBlock | None:
    if isinstance(else_branch, BlockStmt):
        return lower_block(typecheck_ctx, else_branch, symbol_index=symbol_index, local_id_tracker=local_id_tracker)
    if isinstance(else_branch, IfStmt):
        nested_if = lower_stmt(typecheck_ctx, else_branch, symbol_index=symbol_index, local_id_tracker=local_id_tracker)
        return SemanticBlock(statements=[nested_if], span=else_branch.span)
    return None


def _lower_for_in_stmt(
    typecheck_ctx: TypeCheckContext,
    stmt: ForInStmt,
    *,
    symbol_index,
    local_id_tracker: LocalIdTracker,
) -> SemanticForIn:
    collection_type = infer_expression_type(typecheck_ctx, stmt.collection_expr)
    element_type = resolve_for_in_element_type(typecheck_ctx, collection_type, stmt.span)

    push_scope(typecheck_ctx)
    local_id_tracker.push_scope()
    try:
        declare_variable(typecheck_ctx, stmt.element_name, element_type, stmt.span)
        local_id_tracker.declare_local(
            stmt.element_name,
            type_name=element_type.name,
            span=stmt.span,
            binding_kind="for_in_element",
        )
        body = lower_block(typecheck_ctx, stmt.body, symbol_index=symbol_index, local_id_tracker=local_id_tracker)
    finally:
        local_id_tracker.pop_scope()
        pop_scope(typecheck_ctx)

    return SemanticForIn(
        element_name=stmt.element_name,
        collection=lower_expr(typecheck_ctx, symbol_index, stmt.collection_expr, local_id_tracker),
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
