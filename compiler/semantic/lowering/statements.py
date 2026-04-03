from __future__ import annotations

from dataclasses import dataclass

from compiler.common.collection_protocols import CollectionOpKind
from compiler.frontend.ast_nodes import *
from compiler.semantic.ir import *
from compiler.semantic.lowering.ids import constructor_id_from_type_name
from compiler.semantic.lowering.expressions import lower_expr
from compiler.semantic.lowering.locals import LocalIdTracker, LoweringBindingBridge
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.typecheck.call_helpers import select_constructor_overload
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeInfo
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.typecheck.structural import resolve_for_in_element_type
from compiler.typecheck.type_resolution import resolve_type_ref

from compiler.semantic.lowering.collections import resolve_collection_dispatch, try_lower_slice_assign_stmt
from compiler.semantic.lowering.references import lower_lvalue
from compiler.semantic.symbols import ConstructorId, FunctionId, MethodId


@dataclass(frozen=True)
class LoweredFunctionBody:
    body: SemanticBlock
    local_info_by_id: dict[LocalId, SemanticLocalInfo]


def lower_function_like_body(
    typecheck_ctx: TypeCheckContext,
    *,
    owner_id: FunctionId | MethodId | ConstructorId,
    symbol_index,
    params: list[ParamDecl],
    body: BlockStmt,
    receiver_type: TypeInfo | None,
    owner_class_name: str | None,
) -> LoweredFunctionBody:
    local_id_tracker = LocalIdTracker(owner_id=owner_id, typecheck_ctx=typecheck_ctx)
    lowering_bridge = LoweringBindingBridge(typecheck_ctx=typecheck_ctx, local_id_tracker=local_id_tracker)
    with lowering_bridge.private_owner(owner_class_name), lowering_bridge.scope():
        if receiver_type is not None:
            lowering_bridge.declare_receiver(receiver_type, body.span)
        for param in params:
            lowering_bridge.declare_param(param)
        lowered_body = lower_block(typecheck_ctx, body, symbol_index=symbol_index, lowering_bridge=lowering_bridge)
        return LoweredFunctionBody(body=lowered_body, local_info_by_id=lowering_bridge.snapshot_local_info_by_id())


def lower_block(
    typecheck_ctx: TypeCheckContext,
    block: BlockStmt,
    *,
    symbol_index,
    lowering_bridge: LoweringBindingBridge,
) -> SemanticBlock:
    with lowering_bridge.scope():
        return SemanticBlock(
            statements=[
                lower_stmt(typecheck_ctx, stmt, symbol_index=symbol_index, lowering_bridge=lowering_bridge)
                for stmt in block.statements
            ],
            span=block.span,
        )


def lower_stmt(typecheck_ctx: TypeCheckContext, stmt: Statement, *, symbol_index, lowering_bridge: LoweringBindingBridge) -> SemanticStmt:
    if isinstance(stmt, BlockStmt):
        return lower_block(typecheck_ctx, stmt, symbol_index=symbol_index, lowering_bridge=lowering_bridge)

    if isinstance(stmt, VarDeclStmt):
        initializer = (
            None
            if stmt.initializer is None
            else lower_expr(typecheck_ctx, symbol_index, stmt.initializer, lowering_bridge.local_id_tracker)
        )
        var_type = resolve_type_ref(typecheck_ctx, stmt.type_ref)
        local_id = lowering_bridge.declare_local(name=stmt.name, var_type=var_type, span=stmt.span)
        return SemanticVarDecl(
            local_id=local_id,
            initializer=initializer,
            span=stmt.span,
        )

    if isinstance(stmt, IfStmt):
        return SemanticIf(
            condition=lower_expr(typecheck_ctx, symbol_index, stmt.condition, lowering_bridge.local_id_tracker),
            then_block=lower_block(
                typecheck_ctx, stmt.then_branch, symbol_index=symbol_index, lowering_bridge=lowering_bridge
            ),
            else_block=_lower_else_branch(
                typecheck_ctx, stmt.else_branch, symbol_index=symbol_index, lowering_bridge=lowering_bridge
            ),
            span=stmt.span,
        )

    if isinstance(stmt, WhileStmt):
        return SemanticWhile(
            condition=lower_expr(typecheck_ctx, symbol_index, stmt.condition, lowering_bridge.local_id_tracker),
            body=lower_block(typecheck_ctx, stmt.body, symbol_index=symbol_index, lowering_bridge=lowering_bridge),
            span=stmt.span,
        )

    if isinstance(stmt, ForInStmt):
        return _lower_for_in_stmt(typecheck_ctx, stmt, symbol_index=symbol_index, lowering_bridge=lowering_bridge)

    if isinstance(stmt, BreakStmt):
        return SemanticBreak(span=stmt.span)

    if isinstance(stmt, ContinueStmt):
        return SemanticContinue(span=stmt.span)

    if isinstance(stmt, ReturnStmt):
        value = (
            None if stmt.value is None else lower_expr(typecheck_ctx, symbol_index, stmt.value, lowering_bridge.local_id_tracker)
        )
        return SemanticReturn(value=value, span=stmt.span)

    if isinstance(stmt, SuperStmt):
        return _lower_super_stmt(typecheck_ctx, stmt, symbol_index=symbol_index, lowering_bridge=lowering_bridge)

    if isinstance(stmt, AssignStmt):
        return SemanticAssign(
            target=lower_lvalue(
                typecheck_ctx,
                stmt.target,
                lower_expr=lambda nested_expr: lower_expr(
                    typecheck_ctx, symbol_index, nested_expr, lowering_bridge.local_id_tracker
                ),
                local_id_tracker=lowering_bridge.local_id_tracker,
            ),
            value=lower_expr(typecheck_ctx, symbol_index, stmt.value, lowering_bridge.local_id_tracker),
            span=stmt.span,
        )

    if isinstance(stmt, ExprStmt):
        slice_assign = try_lower_slice_assign_stmt(
            typecheck_ctx,
            stmt,
            lower_expr=lambda nested_expr: lower_expr(
                typecheck_ctx, symbol_index, nested_expr, lowering_bridge.local_id_tracker
            ),
        )
        if slice_assign is not None:
            return slice_assign
        return SemanticExprStmt(
            expr=lower_expr(typecheck_ctx, symbol_index, stmt.expression, lowering_bridge.local_id_tracker),
            span=stmt.span,
        )

    raise TypeError(f"Unsupported statement for semantic lowering: {type(stmt).__name__}")


def _lower_else_branch(
    typecheck_ctx: TypeCheckContext,
    else_branch: Statement | None,
    *,
    symbol_index,
    lowering_bridge: LoweringBindingBridge,
) -> SemanticBlock | None:
    if isinstance(else_branch, BlockStmt):
        return lower_block(typecheck_ctx, else_branch, symbol_index=symbol_index, lowering_bridge=lowering_bridge)
    if isinstance(else_branch, IfStmt):
        nested_if = lower_stmt(typecheck_ctx, else_branch, symbol_index=symbol_index, lowering_bridge=lowering_bridge)
        return SemanticBlock(statements=[nested_if], span=else_branch.span)
    return None


def _lower_for_in_stmt(
    typecheck_ctx: TypeCheckContext,
    stmt: ForInStmt,
    *,
    symbol_index,
    lowering_bridge: LoweringBindingBridge,
) -> SemanticForIn:
    lowered_collection = lower_expr(typecheck_ctx, symbol_index, stmt.collection_expr, lowering_bridge.local_id_tracker)
    collection_type = infer_expression_type(typecheck_ctx, stmt.collection_expr)
    element_type = resolve_for_in_element_type(typecheck_ctx, collection_type, stmt.span)

    with lowering_bridge.scope():
        element_local_id = lowering_bridge.declare_local(
            name=stmt.element_name,
            var_type=element_type,
            span=stmt.span,
            binding_kind="for_in_element",
        )
        body = lower_block(typecheck_ctx, stmt.body, symbol_index=symbol_index, lowering_bridge=lowering_bridge)

    return SemanticForIn(
        element_name=stmt.element_name,
        element_local_id=element_local_id,
        collection=lowered_collection,
        iter_len_dispatch=resolve_collection_dispatch(
            typecheck_ctx, collection_type, operation=CollectionOpKind.ITER_LEN
        ),
        iter_get_dispatch=resolve_collection_dispatch(
            typecheck_ctx, collection_type, operation=CollectionOpKind.ITER_GET
        ),
        element_type_ref=semantic_type_ref_from_checked_type(typecheck_ctx, element_type),
        body=body,
        span=stmt.span,
    )


def _lower_super_stmt(
    typecheck_ctx: TypeCheckContext,
    stmt: SuperStmt,
    *,
    symbol_index,
    lowering_bridge: LoweringBindingBridge,
) -> SemanticExprStmt:
    receiver_local_infos = [
        local_info
        for local_info in lowering_bridge.local_id_tracker.local_info_by_id.values()
        if local_info.binding_kind == "receiver"
    ]
    if len(receiver_local_infos) != 1:
        raise ValueError("super(...) lowering requires exactly one receiver local")
    receiver_local_info = receiver_local_infos[0]
    receiver_local_id = receiver_local_info.local_id
    receiver_expr = LocalRefExpr(local_id=receiver_local_id, type_ref=receiver_local_info.type_ref, span=stmt.span)

    receiver_class_info = lookup_class_by_type_name(typecheck_ctx, receiver_local_info.type_ref.canonical_name)
    if receiver_class_info is None or receiver_class_info.superclass_name is None:
        raise ValueError("super(...) lowering requires a checked subclass constructor")

    arg_types = [infer_expression_type(typecheck_ctx, argument) for argument in stmt.arguments]
    constructor_info = select_constructor_overload(
        typecheck_ctx,
        lookup_class_by_type_name(typecheck_ctx, receiver_class_info.superclass_name),
        arg_types,
        stmt.span,
        TypeInfo(name=receiver_class_info.superclass_name, kind="reference"),
    )
    base_constructor_id = constructor_id_from_type_name(typecheck_ctx.module_path, receiver_class_info.superclass_name)
    lowered_arguments = [
        lower_expr(typecheck_ctx, symbol_index, argument, lowering_bridge.local_id_tracker) for argument in stmt.arguments
    ]
    return SemanticExprStmt(
        expr=CallExprS(
            target=ConstructorInitCallTarget(
                constructor_id=ConstructorId(
                    module_path=base_constructor_id.module_path,
                    class_name=base_constructor_id.class_name,
                    ordinal=constructor_info.ordinal,
                ),
                access=BoundMemberAccess(receiver=receiver_expr, receiver_type_ref=receiver_local_info.type_ref),
            ),
            args=lowered_arguments,
            type_ref=semantic_type_ref_from_checked_type(
                typecheck_ctx,
                TypeInfo(name=receiver_class_info.superclass_name, kind="reference"),
            ),
            span=stmt.span,
        ),
        span=stmt.span,
    )
