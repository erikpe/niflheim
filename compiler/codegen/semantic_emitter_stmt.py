from __future__ import annotations

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.asm import offset_operand
from compiler.codegen.semantic_emitter_expr import SemanticEmitContext, emit_expr, infer_expression_type_name
from compiler.codegen.semantic_layout import for_in_temp_name
from compiler.semantic_ir import (
    FieldLValue,
    IndexLValue,
    LocalLValue,
    SemanticAssign,
    SemanticBlock,
    SemanticBreak,
    SemanticContinue,
    SemanticExprStmt,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    SliceLValue,
)


def emit_statement(
    codegen,
    stmt: SemanticStmt,
    epilogue_label: str,
    function_return_type_name: str,
    ctx: SemanticEmitContext,
    loop_labels: list[tuple[str, str]],
) -> None:
    layout = ctx.emit_ctx.layout
    fn_name = ctx.emit_ctx.fn_name
    label_counter = ctx.emit_ctx.label_counter

    codegen.emit_location_comment(
        file_path=stmt.span.start.path,
        line=stmt.span.start.line,
        column=stmt.span.start.column,
    )

    if isinstance(stmt, SemanticReturn):
        if stmt.value is not None:
            emit_expr(codegen, stmt.value, ctx)
        if function_return_type_name == "double":
            codegen.asm.instr("movq xmm0, rax")
        codegen.asm.instr(f"jmp {epilogue_label}")
        return

    if isinstance(stmt, SemanticVarDecl):
        offset = layout.slot_offsets.get(stmt.name)
        if offset is None:
            codegen_types.raise_codegen_error(f"variable '{stmt.name}' is not materialized in stack layout", span=stmt.span)
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

    codegen_types.raise_codegen_error(f"semantic statement codegen not implemented for {type(stmt).__name__}", span=stmt.span)


def _emit_assign(codegen, stmt: SemanticAssign, ctx: SemanticEmitContext) -> None:
    target = stmt.target
    layout = ctx.emit_ctx.layout
    if isinstance(target, LocalLValue):
        offset = layout.slot_offsets.get(target.name)
        if offset is None:
            codegen_types.raise_codegen_error(f"identifier '{target.name}' is not materialized in stack layout", span=stmt.span)
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        return
    if isinstance(target, FieldLValue):
        emit_expr(codegen, target.receiver, ctx)
        codegen.asm.instr("push rax")
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr("pop rcx")
        field_offset = ctx.declaration_tables.class_field_offsets_by_id.get((_class_id_from_type_name(target.receiver_type_name), target.field_name))
        if field_offset is None:
            codegen_types.raise_codegen_error(
                f"field assignment codegen missing field '{target.field_name}' on class '{target.receiver_type_name}'",
                span=stmt.span,
            )
        codegen.asm.instr(f"mov qword ptr [rcx + {field_offset}], rax")
        return
    if isinstance(target, IndexLValue):
        if target.set_method is None:
            target_type = infer_expression_type_name(target.target)
            element_type = codegen_types.array_element_type_name(target_type, span=target.span)
            runtime_name = f"rt_array_set_{codegen_types.array_element_runtime_kind(element_type)}"
            from compiler.codegen.semantic_emitter_expr import _emit_named_call

            _emit_named_call(codegen, runtime_name, [target.target, target.index, stmt.value], "unit", ctx)
            return
        from compiler.codegen.semantic_emitter_expr import _emit_named_call, _method_label

        _emit_named_call(codegen, _method_label(target.set_method, ctx), [target.target, target.index, stmt.value], "unit", ctx)
        return
    if isinstance(target, SliceLValue):
        if target.set_method is None:
            target_type = infer_expression_type_name(target.target)
            element_type = codegen_types.array_element_type_name(target_type, span=target.span)
            runtime_name = f"rt_array_set_slice_{codegen_types.array_element_runtime_kind(element_type)}"
            from compiler.codegen.semantic_emitter_expr import _emit_named_call

            _emit_named_call(codegen, runtime_name, [target.target, target.begin, target.end, stmt.value], "unit", ctx)
            return
        from compiler.codegen.semantic_emitter_expr import _emit_named_call, _method_label

        _emit_named_call(codegen, _method_label(target.set_method, ctx), [target.target, target.begin, target.end, stmt.value], "unit", ctx)
        return


def _emit_for_in(codegen, stmt: SemanticForIn, epilogue_label: str, function_return_type_name: str, ctx: SemanticEmitContext, loop_labels: list[tuple[str, str]]) -> None:
    layout = ctx.emit_ctx.layout
    coll_name = for_in_temp_name("coll", stmt)
    len_name = for_in_temp_name("len", stmt)
    index_name = for_in_temp_name("index", stmt)

    loop_start = codegen_symbols.next_label(ctx.emit_ctx.fn_name, "for_in_start", ctx.emit_ctx.label_counter)
    loop_continue = codegen_symbols.next_label(ctx.emit_ctx.fn_name, "for_in_continue", ctx.emit_ctx.label_counter)
    loop_done = codegen_symbols.next_label(ctx.emit_ctx.fn_name, "for_in_done", ctx.emit_ctx.label_counter)

    emit_expr(codegen, stmt.collection, ctx)
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[coll_name])}, rax")

    from compiler.codegen.semantic_emitter_expr import _emit_named_call, _method_label
    from compiler.semantic_ir import LocalRefExpr

    coll_ref = LocalRefExpr(name=coll_name, type_name=infer_expression_type_name(stmt.collection), span=stmt.span)
    if stmt.iter_len_method is None:
        _emit_named_call(codegen, "rt_array_len", [coll_ref], "u64", ctx)
    else:
        _emit_named_call(codegen, _method_label(stmt.iter_len_method, ctx), [coll_ref], "u64", ctx)
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[len_name])}, rax")
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[index_name])}, 0")

    codegen.asm.label(loop_start)
    codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[index_name])}")
    codegen.asm.instr(f"cmp rax, {offset_operand(layout.slot_offsets[len_name])}")
    codegen.asm.instr(f"jge {loop_done}")

    index_ref = LocalRefExpr(name=index_name, type_name="i64", span=stmt.span)
    if stmt.iter_get_method is None:
        target_type = infer_expression_type_name(stmt.collection)
        element_type = codegen_types.array_element_type_name(target_type, span=stmt.span)
        runtime_name = f"rt_array_get_{codegen_types.array_element_runtime_kind(element_type)}"
        _emit_named_call(codegen, runtime_name, [coll_ref, index_ref], stmt.element_type_name, ctx)
    else:
        _emit_named_call(codegen, _method_label(stmt.iter_get_method, ctx), [coll_ref, index_ref], stmt.element_type_name, ctx)
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.element_name])}, rax")

    loop_labels.append((loop_continue, loop_done))
    emit_statement(codegen, stmt.body, epilogue_label, function_return_type_name, ctx, loop_labels)
    loop_labels.pop()

    codegen.asm.label(loop_continue)
    codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[index_name])}")
    codegen.asm.instr("add rax, 1")
    codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[index_name])}, rax")
    codegen.asm.instr(f"jmp {loop_start}")
    codegen.asm.label(loop_done)


def _class_id_from_type_name(type_name: str):
    from compiler.semantic_symbols import ClassId

    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return ClassId(module_path=tuple(owner_dotted.split(".")), name=class_name)
    return ClassId(module_path=("main",), name=type_name)