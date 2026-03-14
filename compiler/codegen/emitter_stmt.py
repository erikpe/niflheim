from __future__ import annotations

from typing import TYPE_CHECKING

import compiler.codegen.call_resolution as call_resolution
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.ast_nodes import (
    AssignStmt,
    BlockStmt,
    BreakStmt,
    CallExpr,
    ContinueStmt,
    ExprStmt,
    FieldAccessExpr,
    ForInStmt,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    ReturnStmt,
    Statement,
    VarDeclStmt,
    WhileStmt,
)
from compiler.codegen.asm import offset_operand
from compiler.codegen.emitter_expr import emit_call_expr, emit_expr
from compiler.codegen.model import EmitContext

if TYPE_CHECKING:
    from compiler.codegen.legacy import CodeGenerator


def emit_statement(
    codegen: CodeGenerator,
    stmt: Statement,
    epilogue_label: str,
    function_return_type_name: str,
    ctx: EmitContext,
    loop_labels: list[tuple[str, str]],
) -> None:
    layout = ctx.layout
    fn_name = ctx.fn_name
    label_counter = ctx.label_counter

    codegen.emit_location_comment(
        file_path=stmt.span.start.path,
        line=stmt.span.start.line,
        column=stmt.span.start.column,
    )

    if isinstance(stmt, ReturnStmt):
        if stmt.value is not None:
            emit_expr(codegen, stmt.value, ctx)
        if function_return_type_name == "double":
            codegen.asm.instr("movq xmm0, rax")
        codegen.asm.instr(f"jmp {epilogue_label}")
        return

    if isinstance(stmt, ForInStmt):
        loop_start = codegen_symbols.next_label(fn_name, "for_in_start", label_counter)
        loop_continue = codegen_symbols.next_label(fn_name, "for_in_continue", label_counter)
        loop_done = codegen_symbols.next_label(fn_name, "for_in_done", label_counter)

        emit_expr(codegen, stmt.collection_expr, ctx)
        codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.coll_temp_name])}, rax")

        iter_len_call = CallExpr(
            callee=FieldAccessExpr(
                object_expr=IdentifierExpr(name=stmt.coll_temp_name, span=stmt.span),
                field_name="iter_len",
                span=stmt.span,
            ),
            arguments=[],
            span=stmt.span,
        )
        emit_expr(codegen, iter_len_call, ctx)
        codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.len_temp_name])}, rax")
        codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.index_temp_name])}, 0")

        codegen.asm.label(loop_start)
        codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[stmt.index_temp_name])}")
        codegen.asm.instr(f"cmp rax, {offset_operand(layout.slot_offsets[stmt.len_temp_name])}")
        codegen.asm.instr(f"jge {loop_done}")

        iter_get_call = CallExpr(
            callee=FieldAccessExpr(
                object_expr=IdentifierExpr(name=stmt.coll_temp_name, span=stmt.span),
                field_name="iter_get",
                span=stmt.span,
            ),
            arguments=[IdentifierExpr(name=stmt.index_temp_name, span=stmt.span)],
            span=stmt.span,
        )
        emit_expr(codegen, iter_get_call, ctx)
        codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.element_name])}, rax")

        loop_labels.append((loop_continue, loop_done))
        for nested in stmt.body.statements:
            emit_statement(codegen, nested, epilogue_label, function_return_type_name, ctx, loop_labels)
        loop_labels.pop()

        codegen.asm.label(loop_continue)
        codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[stmt.index_temp_name])}")
        codegen.asm.instr("add rax, 1")
        codegen.asm.instr(f"mov {offset_operand(layout.slot_offsets[stmt.index_temp_name])}, rax")
        codegen.asm.instr(f"jmp {loop_start}")
        codegen.asm.label(loop_done)
        return

    if isinstance(stmt, VarDeclStmt):
        offset = layout.slot_offsets.get(stmt.name)
        if offset is None:
            codegen_types.raise_codegen_error(
                f"variable '{stmt.name}' is not materialized in stack layout",
                span=stmt.span,
            )

        if stmt.initializer is None:
            codegen.asm.instr("mov rax, 0")
        else:
            emit_expr(codegen, stmt.initializer, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        return

    if isinstance(stmt, AssignStmt):
        if isinstance(stmt.target, IndexExpr):
            synthetic_callee = FieldAccessExpr(
                object_expr=stmt.target.object_expr,
                field_name="index_set",
                span=stmt.target.span,
            )
            synthetic_call = CallExpr(
                callee=synthetic_callee,
                arguments=[stmt.target.index_expr, stmt.value],
                span=stmt.span,
            )
            emit_call_expr(codegen, synthetic_call, ctx)
            return

        if isinstance(stmt.target, FieldAccessExpr):
            receiver_type_name = call_resolution.field_receiver_type_name(stmt.target.object_expr, ctx)
            if receiver_type_name is None:
                codegen_types.raise_codegen_error("field assignment codegen requires class-typed receiver", span=stmt.span)
            field_offset = codegen.class_field_offsets.get((receiver_type_name, stmt.target.field_name))
            if field_offset is None:
                codegen_types.raise_codegen_error(
                    f"field assignment codegen missing field '{stmt.target.field_name}' on class '{receiver_type_name}'",
                    span=stmt.span,
                )
            emit_expr(codegen, stmt.target.object_expr, ctx)
            codegen.asm.instr("push rax")
            emit_expr(codegen, stmt.value, ctx)
            codegen.asm.instr("pop rcx")
            codegen.asm.instr(f"mov qword ptr [rcx + {field_offset}], rax")
            return

        if not isinstance(stmt.target, IdentifierExpr):
            codegen_types.raise_codegen_error(
                "assignment codegen currently supports identifier, index, or field targets only",
                span=stmt.span,
            )
        offset = layout.slot_offsets.get(stmt.target.name)
        if offset is None:
            codegen_types.raise_codegen_error(
                f"identifier '{stmt.target.name}' is not materialized in stack layout",
                span=stmt.span,
            )
        emit_expr(codegen, stmt.value, ctx)
        codegen.asm.instr(f"mov {offset_operand(offset)}, rax")
        return

    if isinstance(stmt, ExprStmt):
        emit_expr(codegen, stmt.expression, ctx)
        return

    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            emit_statement(codegen, nested, epilogue_label, function_return_type_name, ctx, loop_labels)
        return

    if isinstance(stmt, BreakStmt):
        if not loop_labels:
            codegen_types.raise_codegen_error("break codegen requires enclosing while loop", span=stmt.span)
        _loop_continue_label, loop_end_label = loop_labels[-1]
        codegen.asm.instr(f"jmp {loop_end_label}")
        return

    if isinstance(stmt, ContinueStmt):
        if not loop_labels:
            codegen_types.raise_codegen_error("continue codegen requires enclosing while loop", span=stmt.span)
        loop_continue_label, _loop_end_label = loop_labels[-1]
        codegen.asm.instr(f"jmp {loop_continue_label}")
        return

    if isinstance(stmt, IfStmt):
        else_label = codegen_symbols.next_label(fn_name, "if_else", label_counter)
        end_label = codegen_symbols.next_label(fn_name, "if_end", label_counter)

        emit_expr(codegen, stmt.condition, ctx)
        codegen.asm.instr("cmp rax, 0")
        codegen.asm.instr(f"je {else_label}")
        emit_statement(codegen, stmt.then_branch, epilogue_label, function_return_type_name, ctx, loop_labels)
        codegen.asm.instr(f"jmp {end_label}")
        codegen.asm.label(else_label)
        if stmt.else_branch is not None:
            emit_statement(codegen, stmt.else_branch, epilogue_label, function_return_type_name, ctx, loop_labels)
        codegen.asm.label(end_label)
        return

    if isinstance(stmt, WhileStmt):
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

    codegen_types.raise_codegen_error(f"statement codegen not implemented for {type(stmt).__name__}", span=stmt.span)