"""Structured CFG lowering helpers for phase-2 backend lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from compiler.backend.ir import model as ir_model
from compiler.backend.lowering.expressions import (
    backend_signature_return_type,
    lower_literal_expression_to_operand,
    lower_null_operand,
    lower_unit_operand,
)
from compiler.common.span import SourceSpan
from compiler.semantic.ir import (
    BinaryExprS,
    CallExprS,
    CallableValueCallTarget,
    ClassRefExpr,
    ConstructorCallTarget,
    ConstructorInitCallTarget,
    FieldLValue,
    FieldReadExpr,
    FunctionCallTarget,
    FunctionRefExpr,
    IndexLValue,
    InstanceMethodCallTarget,
    InterfaceMethodCallTarget,
    LocalLValue,
    LocalRefExpr,
    MethodRefExpr,
    NullExprS,
    SemanticAssign,
    SemanticBlock,
    SemanticBreak,
    SemanticContinue,
    SemanticExpr,
    SemanticExprStmt,
    SemanticIf,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    SliceLValue,
    StaticMethodCallTarget,
    UnaryExprS,
    VirtualMethodCallTarget,
)
from compiler.semantic.symbols import ClassId, LocalId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_callable_params,
    semantic_type_callable_return,
    semantic_type_canonical_name,
    semantic_type_is_callable,
)


@dataclass(frozen=True)
class CallableSurface:
    signature: ir_model.BackendSignature
    expects_receiver: bool


@dataclass(frozen=True)
class LoweredBody:
    entry_block_id: ir_model.BackendBlockId
    registers: tuple[ir_model.BackendRegister, ...]
    blocks: tuple[ir_model.BackendBlock, ...]


@dataclass
class _MutableBlock:
    block_id: ir_model.BackendBlockId
    debug_name: str
    span: SourceSpan
    instructions: list[ir_model.BackendInstruction] = field(default_factory=list)
    terminator: ir_model.BackendTerminator | None = None


@dataclass
class _ControlFlowState:
    current_block_id: ir_model.BackendBlockId | None
    reg_by_local_id: dict[LocalId, ir_model.BackendRegId]
    merge_local_ids: frozenset[LocalId]


@dataclass(frozen=True)
class _LoopContext:
    break_target_block_id: ir_model.BackendBlockId
    continue_target_block_id: ir_model.BackendBlockId
    target_reg_by_local_id: dict[LocalId, ir_model.BackendRegId]


@dataclass
class _CallableCFGBuilder:
    callable_id: ir_model.BackendCallableId
    kind: ir_model.BackendCallableKind
    signature: ir_model.BackendSignature
    receiver_reg: ir_model.BackendRegId | None
    home_reg_by_local_id: dict[LocalId, ir_model.BackendRegId]
    registers: list[ir_model.BackendRegister]
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister]
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface]
    next_reg_ordinal: int
    next_inst_ordinal: int = 0
    next_block_ordinal: int = 0
    next_temp_index: int = 0
    blocks: list[_MutableBlock] = field(default_factory=list)
    block_by_id: dict[ir_model.BackendBlockId, _MutableBlock] = field(default_factory=dict)
    loop_stack: list[_LoopContext] = field(default_factory=list)

    def create_block(self, *, debug_name: str, span: SourceSpan) -> ir_model.BackendBlockId:
        block_id = ir_model.BackendBlockId(owner_id=self.callable_id, ordinal=self.next_block_ordinal)
        self.next_block_ordinal += 1
        block = _MutableBlock(block_id=block_id, debug_name=debug_name, span=span)
        self.blocks.append(block)
        self.block_by_id[block_id] = block
        return block_id

    def allocate_temp(self, *, type_ref: SemanticTypeRef, span: SourceSpan, debug_hint: str = "tmp") -> ir_model.BackendRegId:
        reg_id = ir_model.BackendRegId(owner_id=self.callable_id, ordinal=self.next_reg_ordinal)
        self.next_reg_ordinal += 1
        debug_name = f"{debug_hint}{self.next_temp_index}"
        self.next_temp_index += 1
        register = ir_model.BackendRegister(
            reg_id=reg_id,
            type_ref=type_ref,
            debug_name=debug_name,
            origin_kind="temp",
            semantic_local_id=None,
            span=span,
        )
        self.registers.append(register)
        self.register_by_id[reg_id] = register
        return reg_id

    def require_register_type(self, reg_id: ir_model.BackendRegId) -> SemanticTypeRef:
        register = self.register_by_id.get(reg_id)
        if register is None:
            raise KeyError(f"Missing backend register metadata for {reg_id}")
        return register.type_ref

    def require_callable_surface(self, callable_id: ir_model.BackendCallableId) -> CallableSurface:
        surface = self.call_surface_by_id.get(callable_id)
        if surface is None:
            raise KeyError(f"Missing backend callable surface for {callable_id}")
        return surface

    def emit_const(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        constant: ir_model.BackendConstant,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendConstInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                constant=constant,
                span=span,
            )
        )

    def emit_copy(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        source: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendCopyInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                source=source,
                span=span,
            )
        )

    def emit_unary(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        op,
        operand: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendUnaryInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                op=op,
                operand=operand,
                span=span,
            )
        )

    def emit_binary(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        op,
        left: ir_model.BackendOperand,
        right: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendBinaryInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                op=op,
                left=left,
                right=right,
                span=span,
            )
        )

    def emit_call(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId | None,
        target: ir_model.BackendCallTarget,
        args: tuple[ir_model.BackendOperand, ...],
        signature: ir_model.BackendSignature,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendCallInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                target=target,
                args=args,
                signature=signature,
                effects=_conservative_user_call_effects(),
                span=span,
            )
        )

    def emit_alloc_object(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        class_id: ClassId,
        effects: ir_model.BackendEffects,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendAllocObjectInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                class_id=class_id,
                effects=effects,
                span=span,
            )
        )

    def emit_field_load(
        self,
        state: _ControlFlowState,
        *,
        dest: ir_model.BackendRegId,
        object_ref: ir_model.BackendOperand,
        owner_class_id: ClassId,
        field_name: str,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendFieldLoadInst(
                inst_id=self._next_inst_id(),
                dest=dest,
                object_ref=object_ref,
                owner_class_id=owner_class_id,
                field_name=field_name,
                span=span,
            )
        )

    def emit_field_store(
        self,
        state: _ControlFlowState,
        *,
        object_ref: ir_model.BackendOperand,
        owner_class_id: ClassId,
        field_name: str,
        value: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendFieldStoreInst(
                inst_id=self._next_inst_id(),
                object_ref=object_ref,
                owner_class_id=owner_class_id,
                field_name=field_name,
                value=value,
                span=span,
            )
        )

    def emit_null_check(
        self,
        state: _ControlFlowState,
        *,
        value: ir_model.BackendOperand,
        span: SourceSpan,
    ) -> None:
        self._active_block_for(state).instructions.append(
            ir_model.BackendNullCheckInst(
                inst_id=self._next_inst_id(),
                value=value,
                span=span,
            )
        )

    def terminate_with_jump(
        self,
        block_id: ir_model.BackendBlockId,
        *,
        target_block_id: ir_model.BackendBlockId,
        span: SourceSpan,
    ) -> None:
        block = self._mutable_block(block_id)
        if block.terminator is not None:
            raise ValueError(f"Backend block '{block_id}' already has a terminator")
        block.terminator = ir_model.BackendJumpTerminator(span=span, target_block_id=target_block_id)

    def terminate_with_branch(
        self,
        block_id: ir_model.BackendBlockId,
        *,
        condition: ir_model.BackendOperand,
        true_block_id: ir_model.BackendBlockId,
        false_block_id: ir_model.BackendBlockId,
        span: SourceSpan,
    ) -> None:
        block = self._mutable_block(block_id)
        if block.terminator is not None:
            raise ValueError(f"Backend block '{block_id}' already has a terminator")
        block.terminator = ir_model.BackendBranchTerminator(
            span=span,
            condition=condition,
            true_block_id=true_block_id,
            false_block_id=false_block_id,
        )

    def terminate_with_return(
        self,
        block_id: ir_model.BackendBlockId,
        *,
        value: ir_model.BackendOperand | None,
        span: SourceSpan,
    ) -> None:
        block = self._mutable_block(block_id)
        if block.terminator is not None:
            raise ValueError(f"Backend block '{block_id}' already has a terminator")
        block.terminator = ir_model.BackendReturnTerminator(span=span, value=value)

    def freeze_blocks(self) -> tuple[ir_model.BackendBlock, ...]:
        frozen_blocks: list[ir_model.BackendBlock] = []
        for block in self.blocks:
            if block.terminator is None:
                raise ValueError(f"Backend block '{block.block_id}' is missing a terminator")
            frozen_blocks.append(
                ir_model.BackendBlock(
                    block_id=block.block_id,
                    debug_name=block.debug_name,
                    instructions=tuple(block.instructions),
                    terminator=block.terminator,
                    span=block.span,
                )
            )
        return tuple(frozen_blocks)

    def _next_inst_id(self) -> ir_model.BackendInstId:
        inst_id = ir_model.BackendInstId(owner_id=self.callable_id, ordinal=self.next_inst_ordinal)
        self.next_inst_ordinal += 1
        return inst_id

    def _active_block_for(self, state: _ControlFlowState) -> _MutableBlock:
        if state.current_block_id is None:
            raise ValueError("Backend CFG lowering attempted to emit into an unreachable path")
        return self._mutable_block(state.current_block_id)

    def _mutable_block(self, block_id: ir_model.BackendBlockId) -> _MutableBlock:
        block = self.block_by_id.get(block_id)
        if block is None:
            raise KeyError(f"Missing backend block metadata for {block_id}")
        return block


def lower_callable_body(
    *,
    callable_id: ir_model.BackendCallableId,
    kind: ir_model.BackendCallableKind,
    signature: ir_model.BackendSignature,
    receiver_reg: ir_model.BackendRegId | None,
    reg_id_by_local_id: dict[LocalId, ir_model.BackendRegId],
    registers: list[ir_model.BackendRegister],
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    call_surface_by_id: Mapping[ir_model.BackendCallableId, CallableSurface],
    next_reg_ordinal: int,
    body: SemanticBlock | None,
    block_span: SourceSpan,
) -> LoweredBody:
    builder = _CallableCFGBuilder(
        callable_id=callable_id,
        kind=kind,
        signature=signature,
        receiver_reg=receiver_reg,
        home_reg_by_local_id=dict(reg_id_by_local_id),
        registers=list(registers),
        register_by_id=dict(register_by_id),
        call_surface_by_id=call_surface_by_id,
        next_reg_ordinal=next_reg_ordinal,
    )
    entry_block_id = builder.create_block(debug_name="entry", span=block_span)
    state = _ControlFlowState(
        current_block_id=entry_block_id,
        reg_by_local_id=dict(reg_id_by_local_id),
        merge_local_ids=frozenset(),
    )

    if body is not None:
        state = _lower_block(builder, state, body)

    if state.current_block_id is not None:
        if kind == "constructor":
            if receiver_reg is None:
                raise ValueError("Constructor lowering requires a receiver register")
            builder.terminate_with_return(
                state.current_block_id,
                value=ir_model.BackendRegOperand(reg_id=receiver_reg),
                span=block_span,
            )
        elif signature.return_type is None:
            builder.terminate_with_return(state.current_block_id, value=None, span=block_span)
        else:
            raise NotImplementedError(
                f"Backend lowering requires an explicit return for callable '{callable_id}'"
            )

    return LoweredBody(
        entry_block_id=entry_block_id,
        registers=tuple(builder.registers),
        blocks=builder.freeze_blocks(),
    )


def _lower_block(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    block: SemanticBlock,
) -> _ControlFlowState:
    current_state = state
    for statement in block.statements:
        if current_state.current_block_id is None:
            break
        current_state = _lower_stmt(builder, current_state, statement)
    return current_state


def _lower_stmt(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    stmt: SemanticStmt,
) -> _ControlFlowState:
    if isinstance(stmt, SemanticBlock):
        return _lower_block(builder, state, stmt)

    if isinstance(stmt, SemanticVarDecl):
        if stmt.initializer is None:
            return state
        dest_reg_id = _require_local_reg(state, stmt.local_id)
        _materialize_expr_into(builder, state, dest_reg_id=dest_reg_id, expr=stmt.initializer, span=stmt.span)
        return state

    if isinstance(stmt, SemanticAssign):
        if isinstance(stmt.target, LocalLValue):
            dest_reg_id = _assignment_dest_reg(builder, state, stmt.target.local_id, stmt.target.type_ref, stmt.span)
            _materialize_expr_into(builder, state, dest_reg_id=dest_reg_id, expr=stmt.value, span=stmt.span)
            if stmt.target.local_id in state.merge_local_ids:
                state.reg_by_local_id[stmt.target.local_id] = dest_reg_id
            return state

        if isinstance(stmt.target, FieldLValue):
            receiver_operand = _lower_receiver_operand(builder, state, stmt.target.receiver, span=stmt.target.span)
            builder.emit_null_check(state, value=receiver_operand, span=stmt.target.span)
            value_operand = _lower_expression_to_operand(builder, state, stmt.value)
            builder.emit_field_store(
                state,
                object_ref=receiver_operand,
                owner_class_id=stmt.target.owner_class_id,
                field_name=stmt.target.field_name,
                value=value_operand,
                span=stmt.span,
            )
            return state

        if not isinstance(stmt.target, (IndexLValue, SliceLValue)):
            raise NotImplementedError(
                f"Backend lowering does not support assignment target '{type(stmt.target).__name__}' yet"
            )
        raise NotImplementedError(
            f"Backend lowering does not support assignment target '{type(stmt.target).__name__}' yet"
        )

    if isinstance(stmt, SemanticExprStmt):
        _lower_expression_statement(builder, state, stmt.expr, stmt.span)
        return state

    if isinstance(stmt, SemanticReturn):
        _lower_return_stmt(builder, state, stmt)
        return _unreachable_state(state)

    if isinstance(stmt, SemanticIf):
        return _lower_if_stmt(builder, state, stmt)

    if isinstance(stmt, SemanticWhile):
        return _lower_while_stmt(builder, state, stmt)

    if isinstance(stmt, SemanticBreak):
        loop_ctx = _require_loop_context(builder)
        _emit_merge_jump(
            builder,
            state=state,
            target_block_id=loop_ctx.break_target_block_id,
            target_reg_by_local_id=loop_ctx.target_reg_by_local_id,
            merge_local_ids=state.merge_local_ids,
            span=stmt.span,
            debug_name="break.edge",
        )
        return _unreachable_state(state)

    if isinstance(stmt, SemanticContinue):
        loop_ctx = _require_loop_context(builder)
        _emit_merge_jump(
            builder,
            state=state,
            target_block_id=loop_ctx.continue_target_block_id,
            target_reg_by_local_id=loop_ctx.target_reg_by_local_id,
            merge_local_ids=state.merge_local_ids,
            span=stmt.span,
            debug_name="continue.edge",
        )
        return _unreachable_state(state)

    raise NotImplementedError(
        f"Backend lowering does not support statement '{type(stmt).__name__}' yet"
    )


def _lower_if_stmt(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    stmt: SemanticIf,
) -> _ControlFlowState:
    incoming_mapping = dict(state.reg_by_local_id)
    then_block_id = builder.create_block(debug_name="if.then", span=stmt.then_block.span)
    merge_local_ids = frozenset(
        _sorted_local_ids(
            _assigned_local_ids_in_block(stmt.then_block)
            | (set() if stmt.else_block is None else _assigned_local_ids_in_block(stmt.else_block))
        )
    )
    condition = _lower_expression_to_operand(builder, state, stmt.condition)

    if stmt.else_block is None:
        join_block_id = builder.create_block(debug_name="if.end", span=stmt.span)
        builder.terminate_with_branch(
            state.current_block_id,
            condition=condition,
            true_block_id=then_block_id,
            false_block_id=join_block_id,
            span=stmt.condition.span,
        )
        then_state = _ControlFlowState(
            current_block_id=then_block_id,
            reg_by_local_id=dict(incoming_mapping),
            merge_local_ids=state.merge_local_ids | merge_local_ids,
        )
        then_state = _lower_block(builder, then_state, stmt.then_block)
        _emit_merge_jump(
            builder,
            state=then_state,
            target_block_id=join_block_id,
            target_reg_by_local_id=incoming_mapping,
            merge_local_ids=merge_local_ids,
            span=stmt.span,
            debug_name="if.then_to_end",
        )
        return _ControlFlowState(
            current_block_id=join_block_id,
            reg_by_local_id=dict(incoming_mapping),
            merge_local_ids=state.merge_local_ids,
        )

    else_block_id = builder.create_block(debug_name="if.else", span=stmt.else_block.span)
    builder.terminate_with_branch(
        state.current_block_id,
        condition=condition,
        true_block_id=then_block_id,
        false_block_id=else_block_id,
        span=stmt.condition.span,
    )

    then_state = _ControlFlowState(
        current_block_id=then_block_id,
        reg_by_local_id=dict(incoming_mapping),
        merge_local_ids=state.merge_local_ids | merge_local_ids,
    )
    then_state = _lower_block(builder, then_state, stmt.then_block)

    else_state = _ControlFlowState(
        current_block_id=else_block_id,
        reg_by_local_id=dict(incoming_mapping),
        merge_local_ids=state.merge_local_ids | merge_local_ids,
    )
    else_state = _lower_block(builder, else_state, stmt.else_block)

    surviving_edges = [
        ("if.then_to_end", then_state),
        ("if.else_to_end", else_state),
    ]
    surviving_edges = [edge for edge in surviving_edges if edge[1].current_block_id is not None]
    if not surviving_edges:
        return _ControlFlowState(
            current_block_id=None,
            reg_by_local_id=dict(incoming_mapping),
            merge_local_ids=state.merge_local_ids,
        )

    join_block_id = builder.create_block(debug_name="if.end", span=stmt.span)
    for debug_name, branch_state in surviving_edges:
        _emit_merge_jump(
            builder,
            state=branch_state,
            target_block_id=join_block_id,
            target_reg_by_local_id=incoming_mapping,
            merge_local_ids=merge_local_ids,
            span=stmt.span,
            debug_name=debug_name,
        )

    return _ControlFlowState(
        current_block_id=join_block_id,
        reg_by_local_id=dict(incoming_mapping),
        merge_local_ids=state.merge_local_ids,
    )


def _lower_while_stmt(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    stmt: SemanticWhile,
) -> _ControlFlowState:
    incoming_mapping = dict(state.reg_by_local_id)
    cond_block_id = builder.create_block(debug_name="while.cond", span=stmt.span)
    body_block_id = builder.create_block(debug_name="while.body", span=stmt.body.span)
    exit_block_id = builder.create_block(debug_name="while.exit", span=stmt.span)

    builder.terminate_with_jump(
        state.current_block_id,
        target_block_id=cond_block_id,
        span=stmt.span,
    )

    cond_state = _ControlFlowState(
        current_block_id=cond_block_id,
        reg_by_local_id=dict(incoming_mapping),
        merge_local_ids=state.merge_local_ids,
    )
    condition = _lower_expression_to_operand(builder, cond_state, stmt.condition)
    builder.terminate_with_branch(
        cond_block_id,
        condition=condition,
        true_block_id=body_block_id,
        false_block_id=exit_block_id,
        span=stmt.condition.span,
    )

    builder.loop_stack.append(
        _LoopContext(
            break_target_block_id=exit_block_id,
            continue_target_block_id=cond_block_id,
            target_reg_by_local_id=dict(incoming_mapping),
        )
    )
    try:
        body_state = _ControlFlowState(
            current_block_id=body_block_id,
            reg_by_local_id=dict(incoming_mapping),
            merge_local_ids=state.merge_local_ids | frozenset(_sorted_local_ids(_assigned_local_ids_in_block(stmt.body))),
        )
        body_state = _lower_block(builder, body_state, stmt.body)
    finally:
        builder.loop_stack.pop()

    _emit_merge_jump(
        builder,
        state=body_state,
        target_block_id=cond_block_id,
        target_reg_by_local_id=incoming_mapping,
        merge_local_ids=body_state.merge_local_ids,
        span=stmt.span,
        debug_name="while.continue",
    )

    return _ControlFlowState(
        current_block_id=exit_block_id,
        reg_by_local_id=dict(incoming_mapping),
        merge_local_ids=state.merge_local_ids,
    )


def _emit_merge_jump(
    builder: _CallableCFGBuilder,
    *,
    state: _ControlFlowState,
    target_block_id: ir_model.BackendBlockId,
    target_reg_by_local_id: Mapping[LocalId, ir_model.BackendRegId],
    merge_local_ids: frozenset[LocalId],
    span: SourceSpan,
    debug_name: str,
) -> None:
    if state.current_block_id is None:
        return

    copies: list[tuple[ir_model.BackendRegId, ir_model.BackendRegOperand]] = []
    for local_id in _sorted_local_ids(merge_local_ids):
        source_reg_id = state.reg_by_local_id.get(local_id)
        target_reg_id = target_reg_by_local_id.get(local_id)
        if source_reg_id is None or target_reg_id is None or source_reg_id == target_reg_id:
            continue
        copies.append((target_reg_id, ir_model.BackendRegOperand(reg_id=source_reg_id)))

    if not copies:
        builder.terminate_with_jump(state.current_block_id, target_block_id=target_block_id, span=span)
        return

    edge_block_id = builder.create_block(debug_name=debug_name, span=span)
    builder.terminate_with_jump(state.current_block_id, target_block_id=edge_block_id, span=span)
    edge_state = _ControlFlowState(
        current_block_id=edge_block_id,
        reg_by_local_id=dict(target_reg_by_local_id),
        merge_local_ids=frozenset(),
    )
    for dest_reg_id, source_operand in copies:
        builder.emit_copy(edge_state, dest=dest_reg_id, source=source_operand, span=span)
    builder.terminate_with_jump(edge_block_id, target_block_id=target_block_id, span=span)


def _lower_expression_statement(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    expr: SemanticExpr,
    span: SourceSpan,
) -> None:
    if _is_unit_typed(expr.type_ref):
        _lower_expression_to_operand(builder, state, expr)
        return
    if isinstance(expr, (LocalRefExpr, NullExprS)):
        _lower_expression_to_operand(builder, state, expr)
        return
    if hasattr(expr, "constant"):
        _lower_expression_to_operand(builder, state, expr)
        return
    discard_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=span, debug_hint="discard")
    _materialize_expr_into(builder, state, dest_reg_id=discard_reg_id, expr=expr, span=span)


def _materialize_expr_into(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    *,
    dest_reg_id: ir_model.BackendRegId,
    expr: SemanticExpr,
    span: SourceSpan,
) -> None:
    if isinstance(expr, UnaryExprS):
        operand = _lower_expression_to_operand(builder, state, expr.operand)
        builder.emit_unary(state, dest=dest_reg_id, op=expr.op, operand=operand, span=expr.span)
        return
    if isinstance(expr, BinaryExprS):
        left = _lower_expression_to_operand(builder, state, expr.left)
        right = _lower_expression_to_operand(builder, state, expr.right)
        builder.emit_binary(state, dest=dest_reg_id, op=expr.op, left=left, right=right, span=expr.span)
        return
    if isinstance(expr, CallExprS):
        _emit_call_expression(builder, state, expr=expr, dest_reg_id=dest_reg_id)
        return
    if isinstance(expr, FieldReadExpr):
        field_reg_id = _emit_field_read(builder, state, expr)
        if field_reg_id != dest_reg_id:
            builder.emit_copy(
                state,
                dest=dest_reg_id,
                source=ir_model.BackendRegOperand(reg_id=field_reg_id),
                span=span,
            )
        return

    operand = _lower_expression_to_operand(builder, state, expr)
    if isinstance(operand, ir_model.BackendRegOperand):
        if operand.reg_id == dest_reg_id:
            return
        builder.emit_copy(state, dest=dest_reg_id, source=operand, span=span)
        return
    if isinstance(operand, ir_model.BackendConstOperand):
        if isinstance(operand.constant, ir_model.BackendNullConst) and not _is_null_typed(builder.require_register_type(dest_reg_id)):
            raise NotImplementedError(
                "Backend lowering does not materialize null into reference-typed locals yet"
            )
        if isinstance(operand.constant, ir_model.BackendUnitConst):
            raise NotImplementedError("Backend lowering cannot materialize unit-valued expressions into registers")
        builder.emit_const(state, dest=dest_reg_id, constant=operand.constant, span=span)
        return
    raise NotImplementedError(
        f"Backend lowering does not support materializing operand '{type(operand).__name__}' yet"
    )


def _lower_return_stmt(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    stmt: SemanticReturn,
) -> None:
    if stmt.value is None:
        value = None
        if builder.kind == "constructor":
            if builder.receiver_reg is None:
                raise ValueError("Constructor lowering requires a receiver register")
            value = ir_model.BackendRegOperand(reg_id=builder.receiver_reg)
        builder.terminate_with_return(state.current_block_id, value=value, span=stmt.span)
        return

    builder.terminate_with_return(
        state.current_block_id,
        value=_lower_expression_to_operand(builder, state, stmt.value),
        span=stmt.span,
    )


def _lower_expression_to_operand(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    expr: SemanticExpr,
) -> ir_model.BackendOperand:
    if isinstance(expr, LocalRefExpr):
        reg_id = _require_local_reg(state, expr.local_id)
        return ir_model.BackendRegOperand(reg_id=reg_id)
    if isinstance(expr, NullExprS):
        return lower_null_operand()
    if hasattr(expr, "constant"):
        return lower_literal_expression_to_operand(expr)
    if isinstance(expr, UnaryExprS):
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="tmp")
        _materialize_expr_into(builder, state, dest_reg_id=dest_reg_id, expr=expr, span=expr.span)
        return ir_model.BackendRegOperand(reg_id=dest_reg_id)
    if isinstance(expr, BinaryExprS):
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="tmp")
        _materialize_expr_into(builder, state, dest_reg_id=dest_reg_id, expr=expr, span=expr.span)
        return ir_model.BackendRegOperand(reg_id=dest_reg_id)
    if isinstance(expr, FieldReadExpr):
        return ir_model.BackendRegOperand(reg_id=_emit_field_read(builder, state, expr))
    if isinstance(expr, CallExprS):
        return _lower_call_expression(builder, state, expr)
    if isinstance(expr, (FunctionRefExpr, MethodRefExpr, ClassRefExpr)):
        raise NotImplementedError(
            f"Backend lowering does not materialize first-class reference '{type(expr).__name__}' yet"
        )
    raise NotImplementedError(
        f"Backend lowering does not support expression type '{type(expr).__name__}' yet"
    )


def _lower_call_expression(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    expr: CallExprS,
) -> ir_model.BackendOperand:
    dest_reg_id = None
    if _backend_return_type_for_expr(expr) is not None:
        dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="call")
    _emit_call_expression(builder, state, expr=expr, dest_reg_id=dest_reg_id)
    if dest_reg_id is None:
        return lower_unit_operand()
    return ir_model.BackendRegOperand(reg_id=dest_reg_id)


def _emit_call_expression(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    *,
    expr: CallExprS,
    dest_reg_id: ir_model.BackendRegId | None,
) -> None:
    signature = _call_signature(builder, expr)
    target = expr.target

    if isinstance(target, ConstructorCallTarget):
        if dest_reg_id is None:
            raise ValueError("Constructor call lowering requires a destination register")
        args = tuple(_lower_expression_to_operand(builder, state, argument) for argument in expr.args)
        builder.emit_alloc_object(
            state,
            dest=dest_reg_id,
            class_id=_class_id_for_constructor_target(target),
            effects=_conservative_alloc_effects(),
            span=expr.span,
        )
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.constructor_id),
            args=(ir_model.BackendRegOperand(reg_id=dest_reg_id), *args),
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, ConstructorInitCallTarget):
        args = tuple(_lower_expression_to_operand(builder, state, argument) for argument in expr.args)
        receiver_operand = _lower_receiver_operand(builder, state, target.access.receiver, span=target.access.receiver.span)
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.constructor_id),
            args=(receiver_operand, *args),
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, InstanceMethodCallTarget):
        args = _lower_call_args_with_receiver(builder, state, receiver=target.access.receiver, extra_args=expr.args)
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.method_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, VirtualMethodCallTarget):
        args = _lower_call_args_with_receiver(builder, state, receiver=target.access.receiver, extra_args=expr.args)
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendVirtualCallTarget(
                slot_owner_class_id=target.slot_owner_class_id,
                method_name=target.slot_method_name,
                selected_method_id=target.selected_method_id,
            ),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, InterfaceMethodCallTarget):
        args = _lower_call_args_with_receiver(builder, state, receiver=target.access.receiver, extra_args=expr.args)
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendInterfaceCallTarget(interface_id=target.interface_id, method_id=target.method_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    args = tuple(_lower_expression_to_operand(builder, state, argument) for argument in expr.args)

    if isinstance(target, FunctionCallTarget):
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.function_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, StaticMethodCallTarget):
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendDirectCallTarget(callable_id=target.method_id),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    if isinstance(target, CallableValueCallTarget):
        callee = _lower_expression_to_operand(builder, state, target.callee)
        builder.emit_call(
            state,
            dest=dest_reg_id,
            target=ir_model.BackendIndirectCallTarget(callee=callee),
            args=args,
            signature=signature,
            span=expr.span,
        )
        return

    raise NotImplementedError(
        f"Backend lowering does not support call target '{type(target).__name__}' yet"
    )


def _call_signature(builder: _CallableCFGBuilder, expr: CallExprS) -> ir_model.BackendSignature:
    target = expr.target
    if isinstance(target, FunctionCallTarget):
        return builder.require_callable_surface(target.function_id).signature
    if isinstance(target, StaticMethodCallTarget):
        surface = builder.require_callable_surface(target.method_id)
        if surface.expects_receiver:
            raise NotImplementedError("Backend lowering only supports static method direct calls in this slice")
        return surface.signature
    if isinstance(target, InstanceMethodCallTarget):
        surface = builder.require_callable_surface(target.method_id)
        if not surface.expects_receiver:
            raise TypeError("InstanceMethodCallTarget requires a receiver-aware callable surface")
        return surface.signature
    if isinstance(target, VirtualMethodCallTarget):
        surface = builder.require_callable_surface(target.selected_method_id)
        if not surface.expects_receiver:
            raise TypeError("VirtualMethodCallTarget requires a receiver-aware callable surface")
        return surface.signature
    if isinstance(target, InterfaceMethodCallTarget):
        return ir_model.BackendSignature(
            param_types=tuple(argument.type_ref for argument in expr.args),
            return_type=backend_signature_return_type(expr.type_ref),
        )
    if isinstance(target, (ConstructorCallTarget, ConstructorInitCallTarget)):
        return builder.require_callable_surface(target.constructor_id).signature
    if isinstance(target, CallableValueCallTarget):
        callee_type_ref = target.callee.type_ref
        if not semantic_type_is_callable(callee_type_ref):
            raise TypeError("CallableValueCallTarget requires a callable semantic type")
        return ir_model.BackendSignature(
            param_types=semantic_type_callable_params(callee_type_ref),
            return_type=backend_signature_return_type(semantic_type_callable_return(callee_type_ref)),
        )
    raise NotImplementedError(
        f"Backend lowering does not support call target '{type(target).__name__}' yet"
    )


def _assignment_dest_reg(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    local_id: LocalId,
    type_ref: SemanticTypeRef,
    span: SourceSpan,
) -> ir_model.BackendRegId:
    if local_id in state.merge_local_ids:
        return builder.allocate_temp(type_ref=type_ref, span=span, debug_hint="merge")
    return _require_local_reg(state, local_id)


def _require_loop_context(builder: _CallableCFGBuilder) -> _LoopContext:
    if not builder.loop_stack:
        raise ValueError("Backend lowering encountered break/continue outside a loop")
    return builder.loop_stack[-1]


def _require_local_reg(state: _ControlFlowState, local_id: LocalId) -> ir_model.BackendRegId:
    reg_id = state.reg_by_local_id.get(local_id)
    if reg_id is None:
        raise KeyError(f"Missing backend register for semantic local {local_id}")
    return reg_id


def _unreachable_state(state: _ControlFlowState) -> _ControlFlowState:
    return _ControlFlowState(
        current_block_id=None,
        reg_by_local_id=dict(state.reg_by_local_id),
        merge_local_ids=state.merge_local_ids,
    )


def _backend_return_type_for_expr(expr: SemanticExpr) -> SemanticTypeRef | None:
    return backend_signature_return_type(expr.type_ref)


def _emit_field_read(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    expr: FieldReadExpr,
) -> ir_model.BackendRegId:
    receiver_operand = _lower_receiver_operand(builder, state, expr.receiver, span=expr.span)
    builder.emit_null_check(state, value=receiver_operand, span=expr.span)
    dest_reg_id = builder.allocate_temp(type_ref=expr.type_ref, span=expr.span, debug_hint="field")
    builder.emit_field_load(
        state,
        dest=dest_reg_id,
        object_ref=receiver_operand,
        owner_class_id=expr.owner_class_id,
        field_name=expr.field_name,
        span=expr.span,
    )
    return dest_reg_id


def _lower_receiver_operand(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    receiver: SemanticExpr,
    *,
    span: SourceSpan,
) -> ir_model.BackendOperand:
    operand = _lower_expression_to_operand(builder, state, receiver)
    if isinstance(operand, ir_model.BackendRegOperand):
        return operand
    temp_reg_id = builder.allocate_temp(type_ref=receiver.type_ref, span=span, debug_hint="recv")
    _materialize_expr_into(builder, state, dest_reg_id=temp_reg_id, expr=receiver, span=span)
    return ir_model.BackendRegOperand(reg_id=temp_reg_id)


def _lower_call_args_with_receiver(
    builder: _CallableCFGBuilder,
    state: _ControlFlowState,
    *,
    receiver: SemanticExpr,
    extra_args: list[SemanticExpr],
) -> tuple[ir_model.BackendOperand, ...]:
    receiver_operand = _lower_receiver_operand(builder, state, receiver, span=receiver.span)
    return (receiver_operand, *(_lower_expression_to_operand(builder, state, argument) for argument in extra_args))


def _class_id_for_constructor_target(target: ConstructorCallTarget) -> ClassId:
    return ClassId(module_path=target.constructor_id.module_path, name=target.constructor_id.class_name)


def _conservative_alloc_effects() -> ir_model.BackendEffects:
    return ir_model.BackendEffects(writes_memory=True, may_gc=True, may_trap=True)


def _conservative_user_call_effects() -> ir_model.BackendEffects:
    return ir_model.BackendEffects(reads_memory=True, writes_memory=True, may_gc=True, may_trap=True)


def _is_unit_typed(type_ref: SemanticTypeRef) -> bool:
    return semantic_type_canonical_name(type_ref) == "unit"


def _is_null_typed(type_ref: SemanticTypeRef) -> bool:
    return semantic_type_canonical_name(type_ref) == "null"


def _sorted_local_ids(local_ids: set[LocalId] | frozenset[LocalId]) -> tuple[LocalId, ...]:
    return tuple(sorted(local_ids, key=lambda local_id: local_id.ordinal))


def _assigned_local_ids_in_block(block: SemanticBlock) -> set[LocalId]:
    assigned_local_ids: set[LocalId] = set()
    for statement in block.statements:
        assigned_local_ids.update(_assigned_local_ids_in_stmt(statement))
    return assigned_local_ids


def _assigned_local_ids_in_stmt(stmt: SemanticStmt) -> set[LocalId]:
    if isinstance(stmt, SemanticBlock):
        return _assigned_local_ids_in_block(stmt)
    if isinstance(stmt, SemanticAssign):
        if isinstance(stmt.target, LocalLValue):
            return {stmt.target.local_id}
        if isinstance(stmt.target, (IndexLValue, SliceLValue)):
            return set()
        return set()
    if isinstance(stmt, SemanticIf):
        assigned_local_ids = _assigned_local_ids_in_block(stmt.then_block)
        if stmt.else_block is not None:
            assigned_local_ids.update(_assigned_local_ids_in_block(stmt.else_block))
        return assigned_local_ids
    if isinstance(stmt, SemanticWhile):
        return _assigned_local_ids_in_block(stmt.body)
    if isinstance(
        stmt,
        (SemanticVarDecl, SemanticExprStmt, SemanticReturn, SemanticBreak, SemanticContinue),
    ):
        return set()
    raise TypeError(f"Unsupported semantic statement when collecting assigned locals: {type(stmt).__name__}")


__all__ = ["CallableSurface", "LoweredBody", "lower_callable_body"]