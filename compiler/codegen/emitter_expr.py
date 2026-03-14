from __future__ import annotations

from typing import TYPE_CHECKING

import compiler.codegen.call_resolution as call_resolution
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.ast_nodes import (
    ArrayCtorExpr,
    BinaryExpr,
    CallExpr,
    CastExpr,
    Expression,
    FieldAccessExpr,
    IdentifierExpr,
    IndexExpr,
    LiteralExpr,
    NullExpr,
    UnaryExpr,
)
from compiler.codegen.abi_sysv import plan_sysv_arg_locations
from compiler.codegen.asm import offset_operand, stack_slot_operand
from compiler.codegen.model import EmitContext, RUNTIME_REF_ARG_INDICES
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double
from compiler.codegen.ops_int import emit_integer_binary_op, emit_integer_unary_op
from compiler.codegen.strings import STR_CLASS_NAME, decode_char_literal, is_str_type_name

if TYPE_CHECKING:
    from compiler.codegen.legacy import CodeGenerator


def emit_literal_expr(codegen: CodeGenerator, expr: LiteralExpr, ctx: EmitContext) -> None:
    layout = ctx.layout
    label_counter = ctx.label_counter
    string_literal_labels = ctx.string_literal_labels

    if expr.value.startswith('"'):
        label_and_len = string_literal_labels.get(expr.value)
        if label_and_len is None:
            codegen_types._raise_codegen_error("missing string literal lowering metadata", span=expr.span)
        data_label, data_len = label_and_len
        from_u8_label = ctx.method_labels.get((STR_CLASS_NAME, "from_u8_array"))
        if from_u8_label is None or not ctx.method_is_static.get((STR_CLASS_NAME, "from_u8_array"), False):
            codegen_types._raise_codegen_error(
                f"missing static {STR_CLASS_NAME}.from_u8_array for string literal lowering",
                span=expr.span,
            )
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="before",
            label_counter=label_counter,
            line=expr.span.start.line,
            column=expr.span.start.column,
        )
        codegen._emit_root_slot_updates(layout)
        codegen.asm.instr(f"lea rdi, [rip + {data_label}]")
        codegen.asm.instr(f"mov rsi, {data_len}")
        codegen._emit_aligned_call("rt_array_from_bytes_u8")
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="after",
            label_counter=label_counter,
        )
        codegen.asm.instr("mov rdi, rax")
        codegen._emit_aligned_call(from_u8_label)
        return

    if expr.value == "true":
        codegen.asm.instr("mov rax, 1")
        return
    if expr.value == "false":
        codegen.asm.instr("mov rax, 0")
        return
    if codegen_types._is_double_literal_text(expr.value):
        codegen.asm.instr(f"mov rax, 0x{codegen_types._double_literal_bits(expr.value):016x}")
        return
    if expr.value.startswith("'"):
        codegen.asm.instr(f"mov rax, {decode_char_literal(expr.value)}")
        return
    if expr.value.isdigit():
        codegen.asm.instr(f"mov rax, {expr.value}")
        return
    if expr.value.endswith("u8") and expr.value[:-2].isdigit():
        codegen.asm.instr(f"mov rax, {expr.value[:-2]}")
        return
    if expr.value.endswith("u") and expr.value[:-1].isdigit():
        codegen.asm.instr(f"mov rax, {expr.value[:-1]}")
        return

    codegen_types._raise_codegen_error(f"literal codegen not implemented for '{expr.value}'", span=expr.span)


def emit_field_access_expr(codegen: CodeGenerator, expr: FieldAccessExpr, ctx: EmitContext) -> None:
    callable_label = call_resolution._resolve_callable_value_label(expr, ctx)
    if callable_label is not None:
        codegen.asm.instr(f"lea rax, [rip + {callable_label}]")
        return

    receiver_type_name = call_resolution._field_receiver_type_name(expr.object_expr, ctx)
    if receiver_type_name is None:
        codegen_types._raise_codegen_error("field access codegen requires class-typed receiver", span=expr.span)

    field_offset = codegen.class_field_offsets.get((receiver_type_name, expr.field_name))
    if field_offset is None and "::" in receiver_type_name:
        unqualified_type_name = receiver_type_name.split("::", 1)[1]
        field_offset = codegen.class_field_offsets.get((unqualified_type_name, expr.field_name))
    if field_offset is None:
        for (owner_type, field_name), offset in codegen.class_field_offsets.items():
            if field_name != expr.field_name:
                continue
            if owner_type == receiver_type_name or owner_type.endswith(f"::{receiver_type_name}"):
                field_offset = offset
                break
    if field_offset is None:
        codegen_types._raise_codegen_error(
            f"field access codegen missing field '{expr.field_name}' on class '{receiver_type_name}'",
            span=expr.span,
        )
    emit_expr(codegen, expr.object_expr, ctx)
    codegen.asm.instr(f"mov rax, qword ptr [rax + {field_offset}]")


def emit_cast_expr(codegen: CodeGenerator, expr: CastExpr, ctx: EmitContext) -> None:
    label_counter = ctx.label_counter

    emit_expr(codegen, expr.operand, ctx)
    source_type = call_resolution._infer_expression_type_name(expr.operand, ctx)
    target_type = codegen_types._type_ref_name(expr.type_ref)

    if target_type == source_type:
        return

    if target_type == "Obj" and source_type != "null" and codegen_types._is_reference_type_name(source_type):
        return

    if codegen_types._is_array_type_name(target_type) and source_type == "Obj":
        element_type = codegen_types._array_element_type_name(target_type, span=expr.span)
        array_kind_by_element_type = {
            "i64": 1,
            "u64": 2,
            "u8": 3,
            "bool": 4,
            "double": 5,
        }
        expected_kind = array_kind_by_element_type.get(element_type, 6)
        codegen.asm.instr("push rax")
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="before",
            label_counter=label_counter,
            line=expr.span.start.line,
            column=expr.span.start.column,
        )
        codegen.asm.instr("pop rax")
        codegen.asm.instr("mov rdi, rax")
        codegen.asm.instr(f"mov rsi, {expected_kind}")
        codegen._emit_aligned_call("rt_checked_cast_array_kind")
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="after",
            label_counter=label_counter,
        )
        return

    if codegen_types._is_reference_type_name(target_type):
        type_symbol = codegen_symbols._mangle_type_symbol(target_type)
        codegen.asm.instr("push rax")
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="before",
            label_counter=label_counter,
            line=expr.span.start.line,
            column=expr.span.start.column,
        )
        codegen.asm.instr("pop rax")
        codegen.asm.instr("mov rdi, rax")
        codegen.asm.instr(f"lea rsi, [rip + {type_symbol}]")
        codegen._emit_aligned_call("rt_checked_cast")
        codegen._emit_runtime_call_hook(
            fn_name=ctx.fn_name,
            phase="after",
            label_counter=label_counter,
        )
        return

    if target_type == "double" and source_type in {"i64", "u64", "u8", "bool"}:
        codegen.asm.instr("cvtsi2sd xmm0, rax")
        codegen.asm.instr("movq rax, xmm0")
        return

    if source_type == "double" and target_type in {"i64", "u64", "u8", "bool"}:
        codegen.asm.instr("movq xmm0, rax")
        codegen.asm.instr("cvttsd2si rax, xmm0")
        if target_type == "u8":
            codegen.asm.instr("and rax, 255")
        elif target_type == "bool":
            codegen._emit_bool_normalize()
        return

    if target_type == "u8":
        codegen.asm.instr("and rax, 255")
        return

    if target_type == "bool":
        codegen._emit_bool_normalize()


def emit_index_expr(codegen: CodeGenerator, expr: IndexExpr, ctx: EmitContext) -> None:
    receiver_type_name = call_resolution._infer_expression_type_name(expr.object_expr, ctx)

    synthetic_callee = FieldAccessExpr(
        object_expr=expr.object_expr,
        field_name="index_get",
        span=expr.span,
    )
    synthetic_call = CallExpr(
        callee=synthetic_callee,
        arguments=[expr.index_expr],
        span=expr.span,
    )
    if codegen_types._is_array_type_name(receiver_type_name):
        emit_call_expr(codegen, synthetic_call, ctx)
        return
    emit_call_expr(codegen, synthetic_call, ctx)


def emit_array_ctor_expr(codegen: CodeGenerator, expr: ArrayCtorExpr, ctx: EmitContext) -> None:
    from compiler.codegen.model import ARRAY_CONSTRUCTOR_RUNTIME_CALLS

    array_type_name = codegen_types._type_ref_name(expr.element_type_ref)
    if not codegen_types._is_array_type_name(array_type_name):
        codegen_types._raise_codegen_error("array constructor codegen requires array type", span=expr.span)

    element_type_name = codegen_types._array_element_type_name(array_type_name, span=expr.span)
    runtime_kind = codegen_types._array_element_runtime_kind(element_type_name)
    runtime_ctor = ARRAY_CONSTRUCTOR_RUNTIME_CALLS[runtime_kind]

    emit_expr(codegen, expr.length_expr, ctx)
    codegen.asm.instr("push rax")

    codegen._emit_runtime_call_hook(
        fn_name=ctx.fn_name,
        phase="before",
        label_counter=ctx.label_counter,
        line=expr.span.start.line,
        column=expr.span.start.column,
    )
    codegen._emit_root_slot_updates(ctx.layout)
    rooted_runtime_arg_count = codegen._emit_runtime_call_arg_temp_roots(
        ctx.layout,
        runtime_ctor,
        1,
        span=expr.span,
    )
    codegen.asm.instr("pop rdi")
    codegen._emit_aligned_call(runtime_ctor)
    if rooted_runtime_arg_count > 0:
        codegen._emit_clear_runtime_call_arg_temp_roots(ctx.layout, rooted_runtime_arg_count)
    codegen._emit_runtime_call_hook(
        fn_name=ctx.fn_name,
        phase="after",
        label_counter=ctx.label_counter,
    )


def emit_expr(codegen: CodeGenerator, expr: Expression, ctx: EmitContext) -> None:
    layout = ctx.layout

    if isinstance(expr, LiteralExpr):
        emit_literal_expr(codegen, expr, ctx)
        return

    if isinstance(expr, NullExpr):
        codegen.asm.instr("mov rax, 0")
        return

    if isinstance(expr, IdentifierExpr):
        if expr.name in layout.slot_offsets:
            codegen.asm.instr(f"mov rax, {offset_operand(layout.slot_offsets[expr.name])}")
            return

        callable_label = call_resolution._resolve_callable_value_label(expr, ctx)
        if callable_label is not None:
            codegen.asm.instr(f"lea rax, [rip + {callable_label}]")
            return

        codegen_types._raise_codegen_error(
            f"identifier '{expr.name}' is not materialized in stack layout",
            span=expr.span,
        )
        return

    if isinstance(expr, FieldAccessExpr):
        emit_field_access_expr(codegen, expr, ctx)
        return

    if isinstance(expr, CastExpr):
        emit_cast_expr(codegen, expr, ctx)
        return

    if isinstance(expr, IndexExpr):
        emit_index_expr(codegen, expr, ctx)
        return

    if isinstance(expr, ArrayCtorExpr):
        emit_array_ctor_expr(codegen, expr, ctx)
        return

    if isinstance(expr, CallExpr):
        emit_call_expr(codegen, expr, ctx)
        return

    if isinstance(expr, UnaryExpr):
        emit_unary_expr(codegen, expr, ctx)
        return

    if isinstance(expr, BinaryExpr):
        emit_binary_expr(codegen, expr, ctx)
        return

    codegen_types._raise_codegen_error(f"expression codegen not implemented for {type(expr).__name__}", span=expr.span)


def emit_call_expr(codegen: CodeGenerator, expr: CallExpr, ctx: EmitContext) -> None:
    layout = ctx.layout
    fn_name = ctx.fn_name
    label_counter = ctx.label_counter

    callee_type_name = call_resolution._infer_expression_type_name(expr.callee, ctx)
    if codegen_types._is_function_type_name(callee_type_name):
        call_argument_type_names = [call_resolution._infer_expression_type_name(arg, ctx) for arg in expr.arguments]
        reference_arg_indices = {
            index for index, type_name in enumerate(call_argument_type_names) if codegen_types._is_reference_type_name(type_name)
        }
        arg_locations = plan_sysv_arg_locations(call_argument_type_names)
        stack_arg_indices = [
            index
            for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
            if location_kind == "stack"
        ]

        temp_root_base = ctx.temp_root_depth[0]
        rooted_temp_arg_count = 0
        for arg_index in range(len(expr.arguments) - 1, -1, -1):
            arg = expr.arguments[arg_index]
            emit_expr(codegen, arg, ctx)
            codegen.asm.instr("push rax")
            if arg_index in reference_arg_indices:
                codegen._emit_temp_arg_root_from_rsp(
                    layout,
                    temp_root_base + rooted_temp_arg_count,
                    0,
                    span=expr.span,
                )
                rooted_temp_arg_count += 1
                ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count

        emit_expr(codegen, expr.callee, ctx)
        codegen.asm.instr("mov r11, rax")

        codegen._emit_root_slot_updates(layout)

        codegen.asm.instr("mov r10, rsp")
        for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
            arg_offset = arg_index * 8
            arg_operand = stack_slot_operand("r10", arg_offset)
            if location_kind == "int_reg":
                codegen.asm.instr(f"mov {location_register}, {arg_operand}")
            elif location_kind == "float_reg":
                codegen.asm.instr(f"movq {location_register}, {arg_operand}")

        for arg_index in reversed(stack_arg_indices):
            arg_offset = arg_index * 8
            codegen.asm.instr(f"mov rax, {stack_slot_operand('r10', arg_offset)}")
            codegen.asm.instr("push rax")

        codegen._emit_aligned_call("r11")

        temp_arg_slot_count = len(expr.arguments)
        cleanup_slot_count = temp_arg_slot_count + len(stack_arg_indices)
        if cleanup_slot_count > 0:
            codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")
        if rooted_temp_arg_count > 0:
            codegen._emit_clear_temp_root_slots(layout, temp_root_base, rooted_temp_arg_count)
        ctx.temp_root_depth[0] = temp_root_base

        return_type_name = codegen_types._function_type_return_type_name(callee_type_name, span=expr.span)
        if return_type_name == "double":
            codegen.asm.instr("movq rax, xmm0")
        elif return_type_name == "unit":
            codegen.asm.instr("mov rax, 0")
        return

    resolved_target = call_resolution._resolve_call_target_name(expr.callee, ctx)
    target_name = resolved_target.name

    call_arguments = list(expr.arguments)
    if resolved_target.receiver_expr is not None:
        call_arguments = [resolved_target.receiver_expr, *call_arguments]

    is_runtime_call = codegen_symbols._is_runtime_call_name(target_name)
    call_argument_type_names = [call_resolution._infer_expression_type_name(arg, ctx) for arg in call_arguments]
    reference_arg_indices = {
        index for index, type_name in enumerate(call_argument_type_names) if codegen_types._is_reference_type_name(type_name)
    }
    arg_locations = plan_sysv_arg_locations(call_argument_type_names)
    stack_arg_indices = [
        index
        for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
        if location_kind == "stack"
    ]

    temp_root_base = ctx.temp_root_depth[0]

    if is_runtime_call:
        codegen._emit_runtime_call_hook(
            fn_name=fn_name,
            phase="before",
            label_counter=label_counter,
            line=expr.span.start.line,
            column=expr.span.start.column,
        )

    rooted_temp_arg_count = 0
    for arg_index in range(len(call_arguments) - 1, -1, -1):
        arg = call_arguments[arg_index]
        emit_expr(codegen, arg, ctx)
        codegen.asm.instr("push rax")
        if arg_index in reference_arg_indices:
            codegen._emit_temp_arg_root_from_rsp(
                layout,
                temp_root_base + rooted_temp_arg_count,
                0,
                span=expr.span,
            )
            rooted_temp_arg_count += 1
            ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count

    codegen._emit_root_slot_updates(layout)

    codegen.asm.instr("mov r10, rsp")
    for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
        arg_offset = arg_index * 8
        arg_operand = stack_slot_operand("r10", arg_offset)
        if location_kind == "int_reg":
            codegen.asm.instr(f"mov {location_register}, {arg_operand}")
        elif location_kind == "float_reg":
            codegen.asm.instr(f"movq {location_register}, {arg_operand}")

    for arg_index in reversed(stack_arg_indices):
        arg_offset = arg_index * 8
        codegen.asm.instr(f"mov rax, {stack_slot_operand('r10', arg_offset)}")
        codegen.asm.instr("push rax")

    codegen._emit_aligned_call(target_name)

    temp_arg_slot_count = len(call_arguments)
    cleanup_slot_count = temp_arg_slot_count + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")

    if resolved_target.return_type_name == "double":
        codegen.asm.instr("movq rax, xmm0")
    elif resolved_target.return_type_name == "unit":
        codegen.asm.instr("mov rax, 0")

    if rooted_temp_arg_count > 0:
        codegen._emit_clear_temp_root_slots(layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base

    if is_runtime_call:
        codegen._emit_runtime_call_hook(
            fn_name=fn_name,
            phase="after",
            label_counter=label_counter,
        )


def emit_unary_expr(codegen: CodeGenerator, expr: UnaryExpr, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.operand, ctx)
    operand_type_name = call_resolution._infer_expression_type_name(expr.operand, ctx)
    if expr.operator == "-" and operand_type_name == "double":
        emit_unary_negate_double(codegen.asm)
        return
    if emit_integer_unary_op(
        codegen.asm,
        operator=expr.operator,
        operand_type_name=operand_type_name,
        emit_bool_normalize=codegen._emit_bool_normalize,
    ):
        return
    codegen_types._raise_codegen_error(f"unary operator '{expr.operator}' is not supported", span=expr.span)


def emit_logical_binary_expr(
    codegen: CodeGenerator,
    expr: BinaryExpr,
    *,
    fn_name: str,
    label_counter: list[int],
    ctx: EmitContext,
) -> bool:
    if expr.operator not in ("&&", "||"):
        return False

    branch_id = label_counter[0]
    label_counter[0] += 1
    rhs_label = f".L{fn_name}_logic_rhs_{branch_id}"
    done_label = f".L{fn_name}_logic_done_{branch_id}"

    emit_expr(codegen, expr.left, ctx)
    codegen._emit_bool_normalize()
    codegen.asm.instr("cmp rax, 0")
    if expr.operator == "&&":
        codegen.asm.instr(f"jne {rhs_label}")
        codegen.asm.instr("mov rax, 0")
    else:
        codegen.asm.instr(f"je {rhs_label}")
        codegen.asm.instr("mov rax, 1")
    codegen.asm.instr(f"jmp {done_label}")
    codegen.asm.label(rhs_label)
    emit_expr(codegen, expr.right, ctx)
    codegen._emit_bool_normalize()
    codegen.asm.label(done_label)
    return True


def emit_binary_expr(codegen: CodeGenerator, expr: BinaryExpr, ctx: EmitContext) -> None:
    fn_name = ctx.fn_name
    label_counter = ctx.label_counter

    if emit_logical_binary_expr(codegen, expr, fn_name=fn_name, label_counter=label_counter, ctx=ctx):
        return

    left_type_name = call_resolution._infer_expression_type_name(expr.left, ctx)
    right_type_name = call_resolution._infer_expression_type_name(expr.right, ctx)

    if expr.operator == "+" and is_str_type_name(left_type_name) and is_str_type_name(right_type_name):
        synthetic_callee = FieldAccessExpr(
            object_expr=IdentifierExpr(name=STR_CLASS_NAME, span=expr.span),
            field_name="concat",
            span=expr.span,
        )
        synthetic_call = CallExpr(
            callee=synthetic_callee,
            arguments=[expr.left, expr.right],
            span=expr.span,
        )
        emit_call_expr(codegen, synthetic_call, ctx)
        return

    emit_expr(codegen, expr.left, ctx)
    codegen.asm.instr("push rax")
    emit_expr(codegen, expr.right, ctx)
    codegen.asm.instr("mov rcx, rax")
    codegen.asm.instr("pop rax")

    is_double_op = left_type_name == "double" and right_type_name == "double"

    if is_double_op:
        codegen.asm.instr("movq xmm1, rcx")
        codegen.asm.instr("movq xmm0, rax")
        if emit_double_binary_op(codegen.asm, expr.operator):
            return
        codegen_types._raise_codegen_error(
            f"binary operator '{expr.operator}' is not supported for double operands",
            span=expr.span,
        )

    if emit_integer_binary_op(
        codegen.asm,
        operator=expr.operator,
        operand_type_name=left_type_name,
        fn_name=fn_name,
        label_counter=label_counter,
        next_label=codegen_symbols._next_label,
        runtime_panic_message_label=codegen._runtime_panic_message_label,
        emit_aligned_call=codegen._emit_aligned_call,
    ):
        if left_type_name == "u8" and expr.operator in {"+", "-", "*", "**", "/", "%", "&", "|", "^", "<<", ">>"}:
            codegen.asm.instr("and rax, 255")
        return

    codegen_types._raise_codegen_error(f"binary operator '{expr.operator}' is not supported", span=expr.span)