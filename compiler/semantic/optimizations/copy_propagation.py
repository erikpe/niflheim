from __future__ import annotations

from dataclasses import dataclass, field, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *

from .helpers.assigned_locals import assigned_local_ids_in_block
from .helpers.program_structure import rewrite_program_structure


_CopyEnv = dict[LocalId, LocalId]


@dataclass
class _CopyStats:
    successful_propagations: int = 0


@dataclass
class _CopyState:
    aliases: _CopyEnv = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "_CopyState":
        return cls()

    def fork(self) -> "_CopyState":
        return _CopyState(aliases=self.aliases.copy())

    def resolve_alias_source(self, local_id: LocalId) -> LocalId | None:
        return _resolve_alias_source(local_id, self.aliases)

    def invalidate_local(self, local_id: LocalId) -> None:
        _invalidate_local_aliases(self.aliases, local_id)

    def drop_scoped_local(self, local_id: LocalId) -> None:
        self.invalidate_local(local_id)

    def update_local_alias(
        self, owner: SemanticFunctionLike | None, target_local_id: LocalId, value: SemanticExpr | None
    ) -> None:
        self.invalidate_local(target_local_id)

        if owner is None or not isinstance(value, LocalRefExpr):
            return

        source_local_id = self.resolve_alias_source(value.local_id)
        if source_local_id is None or source_local_id == target_local_id:
            return

        if local_type_ref_for_owner(owner, target_local_id) != local_type_ref_for_owner(owner, source_local_id):
            return

        self.aliases[target_local_id] = source_local_id


@dataclass(frozen=True)
class _CopyMerge:
    invalidated_local_ids: frozenset[LocalId] = frozenset()
    alias_updates: _CopyEnv = field(default_factory=dict)

    @classmethod
    def reset(cls, state: _CopyState) -> "_CopyMerge":
        return cls(invalidated_local_ids=frozenset(state.aliases.keys()))

    @classmethod
    def merge_branches(cls, state: _CopyState, *branch_states: _CopyState) -> "_CopyMerge":
        if not branch_states:
            return cls()

        shared_aliases = branch_states[0].aliases.copy()
        for branch_state in branch_states[1:]:
            shared_aliases = {
                local_id: source_local_id
                for local_id, source_local_id in shared_aliases.items()
                if branch_state.aliases.get(local_id) == source_local_id
            }

        preserved_alias_keys = frozenset(shared_aliases.keys())
        invalidated_local_ids = frozenset(
            local_id for local_id in state.aliases if local_id not in preserved_alias_keys
        )
        return cls(invalidated_local_ids=invalidated_local_ids, alias_updates=shared_aliases)

    def apply(self, state: _CopyState) -> _CopyState:
        merged_state = state.fork()
        for local_id in self.invalidated_local_ids:
            merged_state.invalidate_local(local_id)
        merged_state.aliases.update(self.alias_updates)
        return merged_state


def copy_propagation(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _CopyStats()
    propagated_program = rewrite_program_structure(
        program,
        rewrite_field=lambda field: _propagate_field(field, stats),
        rewrite_function=lambda fn: _propagate_function(fn, stats),
        rewrite_method=lambda method: _propagate_method(method, stats),
    )
    logger.debugv(
        1, "Optimization pass copy_propagation performed %d successful propagations", stats.successful_propagations
    )
    return propagated_program


def _propagate_field(field: SemanticField, stats: _CopyStats) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_propagate_expr(field.initializer, _CopyState.empty(), None, stats))


def _propagate_function(fn: SemanticFunction, stats: _CopyStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    return replace(fn, body=_propagate_block(fn.body, _CopyState.empty(), fn, stats))


def _propagate_method(method: SemanticMethod, stats: _CopyStats) -> SemanticMethod:
    return replace(method, body=_propagate_block(method.body, _CopyState.empty(), method, stats))


def _propagate_block(
    block: SemanticBlock, state: _CopyState, owner: SemanticFunctionLike | None, stats: _CopyStats
) -> SemanticBlock:
    propagated_block, _ = _propagate_nested_block(block, state, owner, stats)
    return propagated_block


def _propagate_nested_block(
    block: SemanticBlock, state: _CopyState, owner: SemanticFunctionLike | None, stats: _CopyStats
) -> tuple[SemanticBlock, _CopyState]:
    current_state = state.fork()
    declared_local_ids: set[LocalId] = set()
    propagated_statements: list[SemanticStmt] = []

    for stmt in block.statements:
        propagated_stmt, current_state = _propagate_stmt(stmt, current_state, owner, stats)
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)
        propagated_statements.append(propagated_stmt)

    for local_id in declared_local_ids:
        current_state.drop_scoped_local(local_id)

    return replace(block, statements=propagated_statements), current_state


def _propagate_stmt(
    stmt: SemanticStmt, state: _CopyState, owner: SemanticFunctionLike | None, stats: _CopyStats
) -> tuple[SemanticStmt, _CopyState]:
    if isinstance(stmt, SemanticBlock):
        return _propagate_nested_block(stmt, state, owner, stats)

    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _propagate_expr(stmt.initializer, state, owner, stats)
        next_state = state.fork()
        next_state.update_local_alias(owner, stmt.local_id, initializer)
        return replace(stmt, initializer=initializer), next_state

    if isinstance(stmt, SemanticAssign):
        target = _propagate_lvalue(stmt.target, state, owner, stats)
        value = _propagate_expr(stmt.value, state, owner, stats)
        next_state = state.fork()
        if isinstance(target, LocalLValue):
            next_state.update_local_alias(owner, target.local_id, value)
        return replace(stmt, target=target, value=value), next_state

    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_propagate_expr(stmt.expr, state, owner, stats)), state

    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _propagate_expr(stmt.value, state, owner, stats)
        return replace(stmt, value=value), state

    if isinstance(stmt, SemanticIf):
        then_block, then_state = _propagate_nested_block(stmt.then_block, state, owner, stats)
        else_block = None
        else_state = state
        if stmt.else_block is not None:
            else_block, else_state = _propagate_nested_block(stmt.else_block, state, owner, stats)

        return (
            replace(
                stmt,
                condition=_propagate_expr(stmt.condition, state, owner, stats),
                then_block=then_block,
                else_block=else_block,
            ),
            _CopyMerge.merge_branches(state, then_state, else_state).apply(state),
        )

    if isinstance(stmt, SemanticWhile):
        condition_state = _invariant_loop_copy_state(state, stmt.body)
        return (
            replace(
                stmt,
                condition=_propagate_expr(stmt.condition, condition_state, owner, stats),
                body=_propagate_block(stmt.body, _CopyState.empty(), owner, stats),
            ),
            _CopyMerge.reset(state).apply(state),
        )

    if isinstance(stmt, SemanticForIn):
        return (
            replace(
                stmt,
                collection=_propagate_expr(stmt.collection, state, owner, stats),
                body=_propagate_block(stmt.body, _CopyState.empty(), owner, stats),
            ),
            _CopyMerge.reset(state).apply(state),
        )

    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt, state

    raise TypeError(f"Unsupported semantic statement for copy propagation: {type(stmt).__name__}")


def _propagate_lvalue(
    target: SemanticLValue, state: _CopyState, owner: SemanticFunctionLike | None, stats: _CopyStats
) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(
            target, access=replace(target.access, receiver=_propagate_expr(target.access.receiver, state, owner, stats))
        )
    if isinstance(target, IndexLValue):
        return replace(
            target,
            target=_propagate_expr(target.target, state, owner, stats),
            index=_propagate_expr(target.index, state, owner, stats),
        )
    if isinstance(target, SliceLValue):
        return replace(
            target,
            target=_propagate_expr(target.target, state, owner, stats),
            begin=_propagate_expr(target.begin, state, owner, stats),
            end=_propagate_expr(target.end, state, owner, stats),
        )
    raise TypeError(f"Unsupported semantic lvalue for copy propagation: {type(target).__name__}")


def _propagate_expr(
    expr: SemanticExpr, state: _CopyState, owner: SemanticFunctionLike | None, stats: _CopyStats
) -> SemanticExpr:
    if isinstance(expr, LocalRefExpr):
        if owner is None:
            return expr
        source_local_id = state.resolve_alias_source(expr.local_id)
        if source_local_id is None or source_local_id == expr.local_id:
            return expr
        if local_type_ref_for_owner(owner, source_local_id) != expr.type_ref:
            return expr
        stats.successful_propagations += 1
        return replace(expr, local_id=source_local_id)

    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return expr

    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _propagate_expr(expr.receiver, state, owner, stats)
        return replace(expr, receiver=receiver)

    if isinstance(expr, UnaryExprS):
        return replace(expr, operand=_propagate_expr(expr.operand, state, owner, stats))

    if isinstance(expr, BinaryExprS):
        return replace(
            expr,
            left=_propagate_expr(expr.left, state, owner, stats),
            right=_propagate_expr(expr.right, state, owner, stats),
        )

    if isinstance(expr, CastExprS):
        return replace(expr, operand=_propagate_expr(expr.operand, state, owner, stats))

    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_propagate_expr(expr.operand, state, owner, stats))

    if isinstance(expr, FieldReadExpr):
        return replace(
            expr, access=replace(expr.access, receiver=_propagate_expr(expr.access.receiver, state, owner, stats))
        )

    if isinstance(expr, CallExprS):
        propagated_args = [_propagate_expr(arg, state, owner, stats) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(
                expr,
                target=replace(expr.target, callee=_propagate_expr(expr.target.callee, state, owner, stats)),
                args=propagated_args,
            )
        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=propagated_args)
        return replace(
            expr,
            target=replace(
                expr.target, access=replace(access, receiver=_propagate_expr(access.receiver, state, owner, stats))
            ),
            args=propagated_args,
        )

    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_propagate_expr(expr.target, state, owner, stats))

    if isinstance(expr, IndexReadExpr):
        return replace(
            expr,
            target=_propagate_expr(expr.target, state, owner, stats),
            index=_propagate_expr(expr.index, state, owner, stats),
        )

    if isinstance(expr, SliceReadExpr):
        return replace(
            expr,
            target=_propagate_expr(expr.target, state, owner, stats),
            begin=_propagate_expr(expr.begin, state, owner, stats),
            end=_propagate_expr(expr.end, state, owner, stats),
        )

    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_propagate_expr(expr.length_expr, state, owner, stats))

    raise TypeError(f"Unsupported semantic expression for copy propagation: {type(expr).__name__}")


def _invalidate_local_aliases(env: _CopyEnv, local_id: LocalId) -> None:
    env.pop(local_id, None)
    for alias_local_id, source_local_id in list(env.items()):
        if source_local_id == local_id:
            env.pop(alias_local_id, None)


def _invariant_loop_copy_state(state: _CopyState, body: SemanticBlock) -> _CopyState:
    assigned_local_ids = assigned_local_ids_in_block(body)
    if not assigned_local_ids:
        return state
    return _CopyState(
        aliases={
            target_local_id: source_local_id
            for target_local_id, source_local_id in state.aliases.items()
            if target_local_id not in assigned_local_ids and source_local_id not in assigned_local_ids
        }
    )


def _resolve_alias_source(local_id: LocalId, env: _CopyEnv) -> LocalId | None:
    seen: set[LocalId] = set()
    current_local_id = local_id

    while current_local_id in env:
        if current_local_id in seen:
            return None
        seen.add(current_local_id)
        current_local_id = env[current_local_id]

    return current_local_id
