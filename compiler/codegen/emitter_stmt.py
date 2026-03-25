from __future__ import annotations

from compiler.common.type_names import TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_UNIT
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_expr import EmitContext, emit_expr
from compiler.semantic.ir import *


def emit_statement(
    codegen,
    stmt: SemanticStmt,
    epilogue_label: str,
    function_return_type_name: str,
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
        if function_return_type_name == TYPE_NAME_DOUBLE:
            codegen.asm.instr("movq xmm0, rax")
        codegen.asm.instr(f"jmp {epilogue_label}")
        return

    if isinstance(stmt, SemanticVarDecl):
        offset = layout.local_slot_offsets.get(stmt.local_id)
        if offset is None:
            local_label = stmt.name if stmt.name is not None else str(stmt.local_id)
            codegen_types.raise_codegen_error(
                f"variable '{local_label}' is not materialized in stack layout", span=stmt.span
            )
        if stmt.initializer is None:
            codegen.asm.instr("mov rax, 0")
        else:
            emit_expr(codegen, stmt.initializer, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        return

    if isinstance(stmt, SemanticAssign):
        _emit_assign(codegen, stmt, ctx)
        return

    if isinstance(stmt, SemanticExprStmt):
        emit_expr(codegen, stmt.expr, ctx)
        return

    if isinstance(stmt, SemanticBlock):
        for nested in stmt.statements:
            emit_statement(codegen, nested, epilogue_label, function_return_type_name, ctx, loop_labels)
        return

    if isinstance(stmt, SemanticBreak):
        if not loop_labels:
            codegen_types.raise_codegen_error("break codegen requires enclosing loop", span=stmt.span)
        _loop_continue, loop_end = loop_labels[-1]
        codegen.asm.instr(f"jmp {loop_end}")
        return

    if isinstance(stmt, SemanticContinue):
        if not loop_labels:
            codegen_types.raise_codegen_error("continue codegen requires enclosing loop", span=stmt.span)
        loop_continue, _loop_end = loop_labels[-1]
        codegen.asm.instr(f"jmp {loop_continue}")
        return

    if isinstance(stmt, SemanticIf):
        else_label = codegen_symbols.next_label(fn_name, "if_else", label_counter)
        end_label = codegen_symbols.next_label(fn_name, "if_end", label_counter)
        emit_expr(codegen, stmt.condition, ctx)
        codegen.asm.instr("cmp rax, 0")
        codegen.asm.instr(f"je {else_label}")
        emit_statement(codegen, stmt.then_block, epilogue_label, function_return_type_name, ctx, loop_labels)
        codegen.asm.instr(f"jmp {end_label}")
        codegen.asm.label(else_label)
        if stmt.else_block is not None:
            emit_statement(codegen, stmt.else_block, epilogue_label, function_return_type_name, ctx, loop_labels)
        codegen.asm.label(end_label)
        return

    if isinstance(stmt, SemanticWhile):
        start_label = codegen_symbols.next_label(fn_name, "while_start", label_counter)
        end_label = codegen_symbols.next_label(fn_name, "while_end", label_counter)
        codegen.asm.label(start_label)
        emit_expr(codegen, stmt.condition, ctx)
        codegen.asm.instr("cmp rax, 0")
        codegen.asm.instr(f"je {end_label}")
        loop_labels.append((start_label, end_label))
        emit_statement(codegen, stmt.body, epilogue_label, function_return_type_name, ctx, loop_labels)
        loop_labels.pop()
        codegen.asm.instr(f"jmp {start_label}")
        codegen.asm.label(end_label)
        return

    if isinstance(stmt, SemanticForIn):
        _emit_for_in(codegen, stmt, epilogue_label, function_return_type_name, ctx, loop_labels)
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
            codegen_types.raise_codegen_error(
                f"identifier '{target.name}' is not materialized in stack layout", span=stmt.span
            )
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        return
    if isinstance(target, FieldLValue):
        emit_expr(codegen, target.receiver, ctx)
        codegen.asm.instr("push rax")
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr("pop rcx")
        field_offset = ctx.declaration_tables.class_field_offset(target.owner_class_id, target.field_name)
        if field_offset is None:
            codegen_types.raise_codegen_error(
                f"field assignment codegen missing field '{target.field_name}' on class '{target.owner_class_id.name}'",
                span=stmt.span,
            )
        codegen.asm.instr(f"mov qword ptr [rcx + {field_offset}], rax")
        return
    if isinstance(target, IndexLValue):
        from compiler.codegen.emitter_expr import _dispatch_target_name, _emit_named_call

        _emit_named_call(
            codegen,
            _dispatch_target_name(target.dispatch, ctx),
            [target.target, target.index, stmt.value],
            TYPE_NAME_UNIT,
            ctx,
        )
        return
    if isinstance(target, SliceLValue):
        from compiler.codegen.emitter_expr import _dispatch_target_name, _emit_named_call

        _emit_named_call(
            codegen,
            _dispatch_target_name(target.dispatch, ctx),
            [target.target, target.begin, target.end, stmt.value],
            TYPE_NAME_UNIT,
            ctx,
        )
        return


def _emit_for_in(
    codegen,
    stmt: SemanticForIn,
    epilogue_label: str,
    function_return_type_name: str,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
) -> None:
    layout = ctx.layout
    if ctx.owner is None:
        raise ValueError("for-in statement emission requires function-like local metadata context")
    collection_offset = _require_local_offset(layout, stmt.collection_local_id, label="for-in collection temp", span=stmt.span)
    length_offset = _require_local_offset(layout, stmt.length_local_id, label="for-in length temp", span=stmt.span)
    index_offset = _require_local_offset(layout, stmt.index_local_id, label="for-in index temp", span=stmt.span)
    element_offset = _require_local_offset(layout, stmt.element_local_id, label=stmt.element_name, span=stmt.span)

    loop_start = codegen_symbols.next_label(ctx.fn_name, "for_in_start", ctx.label_counter)
    loop_continue = codegen_symbols.next_label(ctx.fn_name, "for_in_continue", ctx.label_counter)
    loop_done = codegen_symbols.next_label(ctx.fn_name, "for_in_done", ctx.label_counter)

    emit_expr(codegen, stmt.collection, ctx)
    codegen.asm.instr(f"mov {offset_operand(collection_offset)}, rax")

    from compiler.codegen.emitter_expr import _dispatch_target_name, _emit_named_call

    coll_ref = local_ref_expr_for_owner(ctx.owner, stmt.collection_local_id, span=stmt.span)
    _emit_named_call(codegen, _dispatch_target_name(stmt.iter_len_dispatch, ctx), [coll_ref], TYPE_NAME_U64, ctx)
    codegen.asm.instr(f"mov {offset_operand(length_offset)}, rax")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, 0")

    codegen.asm.label(loop_start)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr(f"cmp rax, {offset_operand(length_offset)}")
    codegen.asm.instr(f"jge {loop_done}")

    index_ref = local_ref_expr_for_owner(ctx.owner, stmt.index_local_id, span=stmt.span)
    _emit_named_call(
        codegen, _dispatch_target_name(stmt.iter_get_dispatch, ctx), [coll_ref, index_ref], stmt.element_type_name, ctx
    )
    codegen.asm.instr(f"mov {offset_operand(element_offset)}, rax")

    loop_labels.append((loop_continue, loop_done))
    emit_statement(codegen, stmt.body, epilogue_label, function_return_type_name, ctx, loop_labels)
    loop_labels.pop()

    codegen.asm.label(loop_continue)
    codegen.asm.instr(f"mov rax, {offset_operand(index_offset)}")
    codegen.asm.instr("add rax, 1")
    codegen.asm.instr(f"mov {offset_operand(index_offset)}, rax")
    codegen.asm.instr(f"jmp {loop_start}")
    codegen.asm.label(loop_done)


def _require_local_offset(layout, local_id: LocalId, *, label: str, span) -> int:
    offset = layout.local_slot_offsets.get(local_id)
    if offset is None:
        codegen_types.raise_codegen_error(f"identifier '{label}' is not materialized in stack layout", span=span)
    return offset
