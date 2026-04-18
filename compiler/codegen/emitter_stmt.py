from __future__ import annotations

from compiler.common.type_names import TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_UNIT
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.abi.array import (
    array_length_operand,
    direct_primitive_array_store_operand,
    emit_direct_ref_array_element_store,
    is_direct_primitive_array_runtime_kind,
)
from compiler.codegen.asm import offset_operand
from compiler.codegen.effects import expr_may_execute_gc
from compiler.codegen.emitter_expr import (
    EmitContext,
    _emit_array_direct_element_load,
    _emit_array_index_bounds_check,
    _emit_array_null_check,
    emit_expr,
    pop_preserved_expr_result,
    push_expr_result_for_later_use,
)
from compiler.semantic.lowered_ir import (
    LoweredSemanticBlock,
    LoweredSemanticForIn,
    LoweredSemanticForInStrategy,
    LoweredSemanticIf,
    LoweredSemanticStmt,
    LoweredSemanticWhile,
)
from compiler.semantic.ir import *
from compiler.semantic.types import SemanticTypeRef, semantic_type_canonical_name


def emit_statement(
    codegen,
    stmt: SemanticStmt | LoweredSemanticStmt,
    epilogue_label: str,
    function_return_type_ref: SemanticTypeRef,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
) -> None:
    layout = ctx.layout
    fn_name = ctx.fn_name
    label_counter = ctx.label_counter

    codegen.emit_location_comment(
        file_path=stmt.span.start.path, line=stmt.span.start.line, column=stmt.span.start.column
    )

    if isinstance(stmt, SemanticReturn):
        if stmt.value is not None:
            emit_expr(codegen, stmt.value, ctx)
        if semantic_type_canonical_name(function_return_type_ref) == TYPE_NAME_DOUBLE:
            codegen.asm.instr("movq xmm0, rax")
        codegen.asm.instr(f"jmp {epilogue_label}")
        return

    if isinstance(stmt, SemanticVarDecl):
        offset = layout.local_slot_offsets.get(stmt.local_id)
        if offset is None:
            local_label = (
                str(stmt.local_id) if ctx.owner is None else local_display_name_for_owner(ctx.owner, stmt.local_id)
            )
            codegen_types.raise_codegen_error(
                f"variable '{local_label}' is not materialized in stack layout", span=stmt.span
            )
        if stmt.initializer is None:
            codegen.asm.instr("mov rax, 0")
        else:
            emit_expr(codegen, stmt.initializer, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        if stmt.initializer is not None:
            ctx.mark_named_root_dirty(stmt.local_id)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, SemanticAssign):
        _emit_assign(codegen, stmt, ctx)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, SemanticExprStmt):
        emit_expr(codegen, stmt.expr, ctx)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, (SemanticBlock, LoweredSemanticBlock)):
        for nested in stmt.statements:
            emit_statement(codegen, nested, epilogue_label, function_return_type_ref, ctx, loop_labels)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, SemanticBreak):
        if not loop_labels:
            codegen_types.raise_codegen_error("break codegen requires enclosing loop", span=stmt.span)
        _loop_continue, loop_end = loop_labels[-1]
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        codegen.asm.instr(f"jmp {loop_end}")
        return

    if isinstance(stmt, SemanticContinue):
        if not loop_labels:
            codegen_types.raise_codegen_error("continue codegen requires enclosing loop", span=stmt.span)
        loop_continue, _loop_end = loop_labels[-1]
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        codegen.asm.instr(f"jmp {loop_continue}")
        return

    if isinstance(stmt, LoweredSemanticIf):
        else_label = codegen_symbols.next_label(fn_name, "if_else", label_counter)
        end_label = codegen_symbols.next_label(fn_name, "if_end", label_counter)
        emit_expr(codegen, stmt.condition, ctx)
        condition_dirty = ctx.snapshot_dirty_named_roots()
        condition_cleared = ctx.snapshot_known_cleared_named_roots()
        codegen.asm.instr("cmp rax, 0")
        codegen.asm.instr(f"je {else_label}")
        emit_statement(codegen, stmt.then_block, epilogue_label, function_return_type_ref, ctx, loop_labels)
        then_dirty = ctx.snapshot_dirty_named_roots()
        then_cleared = ctx.snapshot_known_cleared_named_roots()
        codegen.asm.instr(f"jmp {end_label}")
        codegen.asm.label(else_label)
        ctx.restore_dirty_named_roots(condition_dirty)
        ctx.restore_known_cleared_named_roots(condition_cleared)
        if stmt.else_block is not None:
            emit_statement(codegen, stmt.else_block, epilogue_label, function_return_type_ref, ctx, loop_labels)
            else_dirty = ctx.snapshot_dirty_named_roots()
            else_cleared = ctx.snapshot_known_cleared_named_roots()
        else:
            else_dirty = set(condition_dirty)
            else_cleared = set(condition_cleared)
        ctx.merge_dirty_named_roots(then_dirty, else_dirty)
        ctx.intersect_known_cleared_named_roots(then_cleared, else_cleared)
        codegen.asm.label(end_label)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, LoweredSemanticWhile):
        loop_entry_dirty = ctx.snapshot_dirty_named_roots()
        loop_entry_cleared = ctx.snapshot_known_cleared_named_roots()
        start_label = codegen_symbols.next_label(fn_name, "while_start", label_counter)
        end_label = codegen_symbols.next_label(fn_name, "while_end", label_counter)
        codegen.asm.label(start_label)
        emit_expr(codegen, stmt.condition, ctx)
        codegen.asm.instr("cmp rax, 0")
        codegen.asm.instr(f"je {end_label}")
        loop_labels.append((start_label, end_label))
        emit_statement(codegen, stmt.body, epilogue_label, function_return_type_ref, ctx, loop_labels)
        loop_labels.pop()
        codegen.asm.instr(f"jmp {start_label}")
        codegen.asm.label(end_label)
        ctx.merge_dirty_named_roots(loop_entry_dirty, ctx.snapshot_dirty_named_roots())
        ctx.intersect_known_cleared_named_roots(loop_entry_cleared, ctx.snapshot_known_cleared_named_roots())
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    if isinstance(stmt, LoweredSemanticForIn):
        _emit_for_in(codegen, stmt, epilogue_label, function_return_type_ref, ctx, loop_labels)
        _clear_dead_named_roots_if_needed(codegen, ctx, stmt, loop_labels=loop_labels)
        return

    codegen_types.raise_codegen_error(
        f"semantic statement codegen not implemented for {type(stmt).__name__}", span=stmt.span
    )


def _emit_assign(codegen, stmt: SemanticAssign, ctx: EmitContext) -> None:
    target = stmt.target
    layout = ctx.layout
    if isinstance(target, LocalLValue):
        offset = layout.local_slot_offsets.get(target.local_id)
        if offset is None:
            local_label = (
                str(target.local_id) if ctx.owner is None else local_display_name_for_owner(ctx.owner, target.local_id)
            )
            codegen_types.raise_codegen_error(
                f"identifier '{local_label}' is not materialized in stack layout", span=stmt.span
            )
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        if codegen_types.is_reference_type_ref(target.type_ref):
            ctx.mark_named_root_dirty(target.local_id)
        return
    if isinstance(target, FieldLValue):
        emit_expr(codegen, target.receiver, ctx)
        receiver_temp_root_index = push_expr_result_for_later_use(
            codegen,
            target.receiver,
            ctx,
            preserve_across_gc=expr_may_execute_gc(stmt.value),
            span=stmt.span,
        )
        emit_expr(codegen, stmt.value, ctx)
        pop_preserved_expr_result(codegen, ctx, "rcx", temp_root_index=receiver_temp_root_index)
        field_offset = ctx.declaration_tables.class_field_offset(target.owner_class_id, target.field_name)
        if field_offset is None:
            codegen_types.raise_codegen_error(
                f"field assignment codegen missing field '{target.field_name}' on class '{target.owner_class_id.name}'",
                span=stmt.span,
            )
        codegen.asm.instr(f"mov qword ptr [rcx + {field_offset}], rax")
        return
    if isinstance(target, IndexLValue):
        if codegen.collection_fast_paths_enabled and _is_direct_primitive_array_index_write_target(target):
            _emit_direct_primitive_array_index_write(codegen, stmt, target, ctx)
            return
        if codegen.collection_fast_paths_enabled and _is_direct_ref_array_index_write_target(target):
            _emit_direct_ref_array_index_write(codegen, stmt, target, ctx)
            return
        from compiler.codegen.emitter_expr import _emit_dispatch_call, _named_root_sync_local_ids_for_lvalue_call

        _emit_dispatch_call(
            codegen,
            target.dispatch,
            [target.target, target.index, stmt.value],
            TYPE_NAME_UNIT,
            ctx,
            span=stmt.span,
            named_root_local_ids=_named_root_sync_local_ids_for_lvalue_call(ctx, target),
        )
        return
    if isinstance(target, SliceLValue):
        from compiler.codegen.emitter_expr import _emit_dispatch_call, _named_root_sync_local_ids_for_lvalue_call

        _emit_dispatch_call(
            codegen,
            target.dispatch,
            [target.target, target.begin, target.end, stmt.value],
            TYPE_NAME_UNIT,
            ctx,
            span=stmt.span,
            named_root_local_ids=_named_root_sync_local_ids_for_lvalue_call(ctx, target),
        )
        return


def _emit_for_in(
    codegen,
    stmt: LoweredSemanticForIn,
    epilogue_label: str,
    function_return_type_ref: SemanticTypeRef,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
) -> None:
    layout = ctx.layout
    if ctx.owner is None:
        raise ValueError("for-in statement emission requires function-like local metadata context")
    collection_offset = _require_local_offset(
        layout, stmt.collection_local_id, label="for-in collection temp", span=stmt.span
    )
    length_offset = _require_local_offset(layout, stmt.length_local_id, label="for-in length temp", span=stmt.span)
    index_offset = _require_local_offset(layout, stmt.index_local_id, label="for-in index temp", span=stmt.span)
    element_offset = _require_local_offset(layout, stmt.element_local_id, label=stmt.element_name, span=stmt.span)

    loop_start = codegen_symbols.next_label(ctx.fn_name, "for_in_start", ctx.label_counter)
    loop_continue = codegen_symbols.next_label(ctx.fn_name, "for_in_continue", ctx.label_counter)
    loop_done = codegen_symbols.next_label(ctx.fn_name, "for_in_done", ctx.label_counter)

    emit_expr(codegen, stmt.collection, ctx)
    codegen.asm.instr(f"mov {offset_operand(collection_offset)}, rax")
    ctx.mark_named_root_dirty(stmt.collection_local_id)

    if stmt.strategy is LoweredSemanticForInStrategy.ARRAY_DIRECT and codegen.collection_fast_paths_enabled:
        _emit_array_direct_for_in(
            codegen,
            stmt,
            epilogue_label,
            function_return_type_ref,
            ctx,
            loop_labels,
            collection_offset=collection_offset,
            length_offset=length_offset,
            index_offset=index_offset,
            element_offset=element_offset,
            loop_start=loop_start,
            loop_continue=loop_continue,
            loop_done=loop_done,
        )
        return

    from compiler.codegen.emitter_expr import _emit_dispatch_call

    coll_ref = local_ref_expr_for_owner(ctx.owner, stmt.collection_local_id, span=stmt.span)
    iter_len_named_roots = None if ctx.named_root_liveness is None else ctx.named_root_liveness.for_for_in_iter_len(stmt)
    _emit_dispatch_call(
        codegen,
        stmt.iter_len_dispatch,
        [coll_ref],
        TYPE_NAME_U64,
        ctx,
        span=stmt.span,
        named_root_local_ids=iter_len_named_roots,
    )
    codegen.asm.instr(f"mov {offset_operand(length_offset)}, rax")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, 0")

    codegen.asm.label(loop_start)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr(f"cmp rax, {offset_operand(length_offset)}")
    codegen.asm.instr(f"jge {loop_done}")

    index_ref = local_ref_expr_for_owner(ctx.owner, stmt.index_local_id, span=stmt.span)
    iter_get_named_roots = None if ctx.named_root_liveness is None else ctx.named_root_liveness.for_for_in_iter_get(stmt)
    _emit_dispatch_call(
        codegen,
        stmt.iter_get_dispatch,
        [coll_ref, index_ref],
        stmt.element_type_ref,
        ctx,
        span=stmt.span,
        named_root_local_ids=iter_get_named_roots,
    )
    codegen.asm.instr(f"mov {offset_operand(element_offset)}, rax")
    if codegen_types.is_reference_type_ref(stmt.element_type_ref):
        ctx.mark_named_root_dirty(stmt.element_local_id)

    loop_labels.append((loop_continue, loop_done))
    emit_statement(codegen, stmt.body, epilogue_label, function_return_type_ref, ctx, loop_labels)
    loop_labels.pop()

    codegen.asm.label(loop_continue)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr("add rax, 1")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, rax")
    codegen.asm.instr(f"jmp {loop_start}")
    codegen.asm.label(loop_done)
    ctx.invalidate_all_named_roots()


def _is_direct_primitive_array_index_write_target(target: IndexLValue) -> bool:
    return (
        isinstance(target.dispatch, RuntimeDispatch)
        and target.dispatch.operation is CollectionOpKind.INDEX_SET
        and is_direct_primitive_array_runtime_kind(target.dispatch.runtime_kind)
    )


def _emit_direct_primitive_array_index_write(
    codegen,
    stmt: SemanticAssign,
    target: IndexLValue,
    ctx: EmitContext,
) -> None:
    assert isinstance(target.dispatch, RuntimeDispatch)
    runtime_kind = target.dispatch.runtime_kind
    if runtime_kind is None:
        codegen_types.raise_codegen_error("direct primitive array write requires runtime kind", span=stmt.span)

    emit_expr(codegen, stmt.value, ctx)
    codegen.emit_push("rax")
    emit_expr(codegen, target.index, ctx)
    codegen.emit_push("rax")
    emit_expr(codegen, target.target, ctx)

    codegen.emit_pop("rcx")
    codegen.emit_pop("rdx")
    _emit_array_null_check(codegen, ctx=ctx)
    _emit_array_index_bounds_check(codegen, target.dispatch, ctx=ctx)
    _emit_direct_primitive_array_store(
        codegen,
        runtime_kind,
        array_register="rax",
        index_register="rcx",
    )


def _emit_direct_primitive_array_store(
    codegen,
    runtime_kind: ArrayRuntimeKind,
    *,
    array_register: str,
    index_register: str,
) -> None:
    store_operand = direct_primitive_array_store_operand(
        array_register,
        index_register,
        runtime_kind=runtime_kind,
    )
    if runtime_kind is ArrayRuntimeKind.BOOL:
        codegen.asm.instr("test rdx, rdx")
        codegen.asm.instr("setne dl")
        codegen.asm.instr("movzx edx, dl")
    if runtime_kind is ArrayRuntimeKind.U8:
        codegen.asm.instr(f"mov {store_operand}, dl")
        return
    codegen.asm.instr(f"mov {store_operand}, rdx")


def _is_direct_ref_array_index_write_target(target: IndexLValue) -> bool:
    return (
        isinstance(target.dispatch, RuntimeDispatch)
        and target.dispatch.operation is CollectionOpKind.INDEX_SET
        and target.dispatch.runtime_kind is ArrayRuntimeKind.REF
    )


def _emit_direct_ref_array_index_write(
    codegen,
    stmt: SemanticAssign,
    target: IndexLValue,
    ctx: EmitContext,
) -> None:
    temp_root_base = ctx.temp_root_depth[0]
    needs_temp_root = _direct_ref_array_write_value_needs_temp_root(target)

    emit_expr(codegen, stmt.value, ctx)
    if needs_temp_root:
        _emit_temp_root_slot_move(codegen, ctx, temp_root_base, source_register="rax", span=stmt.span)
        ctx.temp_root_depth[0] = temp_root_base + 1
    codegen.emit_push("rax")
    emit_expr(codegen, target.index, ctx)
    codegen.emit_push("rax")
    emit_expr(codegen, target.target, ctx)

    codegen.emit_pop("rcx")
    codegen.emit_pop("rdx")
    _emit_array_null_check(codegen, ctx=ctx)
    _emit_array_index_bounds_check(codegen, target.dispatch, ctx=ctx)
    emit_direct_ref_array_element_store(
        codegen,
        array_register="rax",
        index_register="rcx",
        value_register="rdx",
    )
    if needs_temp_root:
        codegen.emit_clear_temp_root_slots(ctx.layout, temp_root_base, 1)
        ctx.temp_root_depth[0] = temp_root_base


def _direct_ref_array_write_value_needs_temp_root(target: IndexLValue) -> bool:
    return any(expr_may_execute_gc(expr) for expr in (target.index, target.target))


def _emit_temp_root_slot_move(
    codegen,
    ctx: EmitContext,
    temp_slot_index: int,
    *,
    source_register: str,
    span,
) -> None:
    if temp_slot_index >= len(ctx.layout.temp_root_slot_offsets):
        codegen_types.raise_codegen_error("insufficient temporary root slots for ref[] fast write", span=span)
    codegen.asm.instr(f"mov {offset_operand(ctx.layout.temp_root_slot_offsets[temp_slot_index])}, {source_register}")


def _emit_array_direct_for_in(
    codegen,
    stmt: LoweredSemanticForIn,
    epilogue_label: str,
    function_return_type_ref: SemanticTypeRef,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
    *,
    collection_offset: int,
    length_offset: int,
    index_offset: int,
    element_offset: int,
    loop_start: str,
    loop_continue: str,
    loop_done: str,
) -> None:
    codegen.asm.instr(f"mov rax, {offset_operand(collection_offset)}")
    _emit_array_null_check(codegen, ctx=ctx)
    codegen.asm.instr(f"mov rax, {array_length_operand('rax')}")
    codegen.asm.instr(f"mov {offset_operand(length_offset)}, rax")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, 0")

    codegen.asm.label(loop_start)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr(f"cmp rax, {offset_operand(length_offset)}")
    codegen.asm.instr(f"jge {loop_done}")

    codegen.asm.instr(f"mov rcx, {offset_operand(collection_offset)}")
    _emit_array_direct_element_load(
        codegen,
        stmt.element_type_ref,
        array_register="rcx",
        index_register="rax",
        span=stmt.span,
    )
    _emit_loaded_for_in_element(
        codegen,
        stmt,
        epilogue_label,
        function_return_type_ref,
        ctx,
        loop_labels,
        element_offset=element_offset,
        index_offset=index_offset,
        loop_continue=loop_continue,
        loop_done=loop_done,
        loop_start=loop_start,
    )


def _emit_loaded_for_in_element(
    codegen,
    stmt: LoweredSemanticForIn,
    epilogue_label: str,
    function_return_type_ref: SemanticTypeRef,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
    *,
    element_offset: int,
    index_offset: int,
    loop_continue: str,
    loop_done: str,
    loop_start: str,
) -> None:
    codegen.asm.instr(f"mov {offset_operand(element_offset)}, rax")
    if codegen_types.is_reference_type_ref(stmt.element_type_ref):
        ctx.mark_named_root_dirty(stmt.element_local_id)

    loop_labels.append((loop_continue, loop_done))
    emit_statement(codegen, stmt.body, epilogue_label, function_return_type_ref, ctx, loop_labels)
    loop_labels.pop()

    codegen.asm.label(loop_continue)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr("add rax, 1")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, rax")
    codegen.asm.instr(f"jmp {loop_start}")
    codegen.asm.label(loop_done)
    ctx.invalidate_all_named_roots()


def _require_local_offset(layout, local_id: LocalId, *, label: str, span) -> int:
    offset = layout.local_slot_offsets.get(local_id)
    if offset is None:
        codegen_types.raise_codegen_error(f"identifier '{label}' is not materialized in stack layout", span=span)
    return offset


def _clear_dead_named_roots_if_needed(
    codegen,
    ctx: EmitContext,
    stmt: SemanticStmt | LoweredSemanticStmt,
    *,
    loop_labels: list[tuple[str, str]],
) -> None:
    if ctx.named_root_liveness is None or ctx.known_cleared_named_root_local_ids is None:
        return
    if loop_labels:
        return

    live_local_ids = ctx.named_root_liveness.for_stmt(stmt)
    live_slot_indices = {
        slot_index
        for local_id in live_local_ids
        for slot_index in [ctx.layout.named_root_slot_plan.for_local(local_id)]
        if slot_index is not None
    }
    local_ids_to_clear = frozenset(
        local_id
        for local_id in ctx.tracked_named_root_local_ids
        if local_id not in live_local_ids and local_id not in ctx.known_cleared_named_root_local_ids
        and ctx.layout.named_root_slot_plan.for_local(local_id) not in live_slot_indices
    )
    if not local_ids_to_clear:
        return

    codegen.emit_named_root_slot_clears(ctx.layout, local_ids=local_ids_to_clear)
    ctx.mark_named_roots_cleared(local_ids_to_clear)
