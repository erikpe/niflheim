from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.abi_sysv import plan_sysv_arg_locations
from compiler.codegen.asm import offset_operand, stack_slot_operand
from compiler.codegen.model import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_GET_RUNTIME_CALLS,
    ARRAY_SLICE_RUNTIME_CALLS,
    FunctionLayout,
)
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double
from compiler.codegen.ops_int import emit_integer_binary_op, emit_integer_unary_op
from compiler.semantic_ir import (
    ArrayCtorExprS,
    BinaryExprS,
    CallableValueCallExpr,
    CastExprS,
    ClassRefExpr,
    ConstructorCallExpr,
    FieldReadExpr,
    FunctionCallExpr,
    FunctionRefExpr,
    ArrayLenExpr,
    IndexReadExpr,
    InstanceMethodCallExpr,
    LiteralExprS,
    LocalRefExpr,
    MethodRefExpr,
    NullExprS,
    SemanticExpr,
    SliceReadExpr,
    StaticMethodCallExpr,
    SyntheticExpr,
    UnaryExprS,
)
from compiler.semantic_symbols import MethodId

if TYPE_CHECKING:
    from compiler.codegen.generator import CodeGenerator
    from compiler.codegen.program_generator import DeclarationTables


@dataclass
class EmitContext:
    layout: FunctionLayout
    fn_name: str
    label_counter: list[int]
    string_literal_labels: dict[str, tuple[str, int]]
    temp_root_depth: list[int]
    declaration_tables: DeclarationTables


def infer_expression_type_name(expr: SemanticExpr) -> str:
    if isinstance(expr, LocalRefExpr):
        return expr.type_name
    if isinstance(expr, FunctionRefExpr):
        return expr.type_name
    if isinstance(expr, ClassRefExpr):
        return expr.type_name
    if isinstance(expr, MethodRefExpr):
        return expr.type_name
    if isinstance(expr, LiteralExprS):
        return expr.type_name
    if isinstance(expr, NullExprS):
        return "null"
    if isinstance(expr, UnaryExprS):
        return expr.type_name
    if isinstance(expr, BinaryExprS):
        return expr.type_name
    if isinstance(expr, CastExprS):
        return expr.type_name
    if isinstance(expr, FieldReadExpr):
        return expr.field_type_name
    if isinstance(expr, FunctionCallExpr):
        return expr.type_name
    if isinstance(expr, StaticMethodCallExpr):
        return expr.type_name
    if isinstance(expr, InstanceMethodCallExpr):
        return expr.type_name
    if isinstance(expr, ConstructorCallExpr):
        return expr.type_name
    if isinstance(expr, CallableValueCallExpr):
        return expr.type_name
    if isinstance(expr, ArrayLenExpr):
        return "u64"
    if isinstance(expr, IndexReadExpr):
        return expr.result_type_name
    if isinstance(expr, SliceReadExpr):
        return expr.result_type_name
    if isinstance(expr, ArrayCtorExprS):
        return expr.type_name
    if isinstance(expr, SyntheticExpr):
        return expr.type_name
    raise TypeError(f"Unsupported semantic expression: {type(expr).__name__}")


def emit_expr(codegen: CodeGenerator, expr: SemanticExpr, ctx: EmitContext) -> None:
    if isinstance(expr, LiteralExprS):
        _emit_literal_expr(codegen, expr)
        return
    if isinstance(expr, NullExprS):
        codegen.asm.instr("mov rax, 0")
        return
    if isinstance(expr, LocalRefExpr):
        _emit_local_ref_expr(codegen, expr, ctx)
        return
    if isinstance(expr, FunctionRefExpr):
        codegen.asm.instr(f"lea rax, [rip + {expr.function_id.name}]")
        return
    if isinstance(expr, MethodRefExpr):
        _emit_method_ref_expr(codegen, expr, ctx)
        return
    if isinstance(expr, ClassRefExpr):
        codegen_types.raise_codegen_error("class reference codegen is not implemented for semantic IR", span=expr.span)
    if isinstance(expr, FieldReadExpr):
        _emit_field_read_expr(codegen, expr, ctx)
        return
    if isinstance(expr, CastExprS):
        _emit_cast_expr(codegen, expr, ctx)
        return
    if isinstance(expr, ArrayCtorExprS):
        _emit_array_ctor_expr(codegen, expr, ctx)
        return
    if isinstance(expr, FunctionCallExpr):
        _emit_named_call(codegen, expr.function_id.name, expr.args, expr.type_name, ctx)
        return
    if isinstance(expr, StaticMethodCallExpr):
        _emit_named_call(codegen, _method_label(expr.method_id, ctx), expr.args, expr.type_name, ctx)
        return
    if isinstance(expr, InstanceMethodCallExpr):
        _emit_named_call(codegen, _method_label(expr.method_id, ctx), [expr.receiver, *expr.args], expr.type_name, ctx)
        return
    if isinstance(expr, ConstructorCallExpr):
        _emit_named_call(codegen, _constructor_label(expr.constructor_id.class_name), expr.args, expr.type_name, ctx)
        return
    if isinstance(expr, CallableValueCallExpr):
        _emit_callable_value_call(codegen, expr, ctx)
        return
    if isinstance(expr, ArrayLenExpr):
        _emit_named_call(codegen, "rt_array_len", [expr.target], "u64", ctx)
        return
    if isinstance(expr, IndexReadExpr):
        _emit_index_read_expr(codegen, expr, ctx)
        return
    if isinstance(expr, SliceReadExpr):
        _emit_slice_read_expr(codegen, expr, ctx)
        return
    if isinstance(expr, SyntheticExpr):
        _emit_synthetic_expr(codegen, expr, ctx)
        return
    if isinstance(expr, UnaryExprS):
        _emit_unary_expr(codegen, expr, ctx)
        return
    if isinstance(expr, BinaryExprS):
        _emit_binary_expr(codegen, expr, ctx)
        return
    codegen_types.raise_codegen_error(
        f"semantic expression codegen not implemented for {type(expr).__name__}", span=expr.span
    )


def _emit_local_ref_expr(codegen: CodeGenerator, expr: LocalRefExpr, ctx: EmitContext) -> None:
    offset = ctx.layout.slot_offsets.get(expr.name)
    if offset is None:
        codegen_types.raise_codegen_error(
            f"identifier '{expr.name}' is not materialized in stack layout", span=expr.span
        )
    codegen.asm.instr(f"mov rax, {offset_operand(offset)}")


def _emit_method_ref_expr(codegen: CodeGenerator, expr: MethodRefExpr, ctx: EmitContext) -> None:
    if expr.receiver is not None:
        codegen_types.raise_codegen_error("bound instance method references are not implemented", span=expr.span)
    codegen.asm.instr(f"lea rax, [rip + {_method_label(expr.method_id, ctx)}]")


def _emit_literal_expr(codegen: CodeGenerator, expr: LiteralExprS) -> None:
    if expr.value == "true":
        codegen.asm.instr("mov rax, 1")
        return
    if expr.value == "false":
        codegen.asm.instr("mov rax, 0")
        return
    if codegen_types.is_double_literal_text(expr.value):
        codegen.asm.instr(f"mov rax, 0x{codegen_types.double_literal_bits(expr.value):016x}")
        return
    if expr.value.startswith("'"):
        from compiler.codegen.strings import decode_char_literal

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
    codegen_types.raise_codegen_error(f"literal codegen not implemented for '{expr.value}'", span=expr.span)


def _emit_field_read_expr(codegen: CodeGenerator, expr: FieldReadExpr, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.receiver, ctx)
    field_offset = _resolve_field_offset(ctx, expr.receiver_type_name, expr.field_name)
    if field_offset is None:
        codegen_types.raise_codegen_error(
            f"field access codegen missing field '{expr.field_name}' on class '{expr.receiver_type_name}'",
            span=expr.span,
        )
    codegen.asm.instr(f"mov rax, qword ptr [rax + {field_offset}]")


def _emit_cast_expr(codegen: CodeGenerator, expr: CastExprS, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.operand, ctx)
    source_type = infer_expression_type_name(expr.operand)
    target_type = expr.target_type_name
    if target_type == source_type:
        return
    if target_type == "Obj" and source_type != "null" and codegen_types.is_reference_type_name(source_type):
        return
    if codegen_types.is_array_type_name(target_type) and source_type == "Obj":
        element_type = codegen_types.array_element_type_name(target_type, span=expr.span)
        array_kind_by_element_type = {"i64": 1, "u64": 2, "u8": 3, "bool": 4, "double": 5}
        expected_kind = array_kind_by_element_type.get(element_type, 6)
        codegen.asm.instr("push rax")
        _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
        codegen.asm.instr("pop rax")
        codegen.asm.instr("mov rdi, rax")
        codegen.asm.instr(f"mov rsi, {expected_kind}")
        codegen.emit_aligned_call("rt_checked_cast_array_kind")
        _emit_runtime_call_hooks_after(codegen, ctx)
        return
    if codegen_types.is_reference_type_name(target_type):
        codegen.asm.instr("push rax")
        _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
        codegen.asm.instr("pop rax")
        codegen.asm.instr("mov rdi, rax")
        codegen.asm.instr(f"lea rsi, [rip + {codegen_symbols.mangle_type_symbol(target_type)}]")
        codegen.emit_aligned_call("rt_checked_cast")
        _emit_runtime_call_hooks_after(codegen, ctx)
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
            codegen.emit_bool_normalize()
        return
    if target_type == "u8":
        codegen.asm.instr("and rax, 255")
        return
    if target_type == "bool":
        codegen.emit_bool_normalize()


def _emit_array_ctor_expr(codegen: CodeGenerator, expr: ArrayCtorExprS, ctx: EmitContext) -> None:
    runtime_kind = codegen_types.array_element_runtime_kind(expr.element_type_name)
    runtime_ctor = ARRAY_CONSTRUCTOR_RUNTIME_CALLS[runtime_kind]
    emit_expr(codegen, expr.length_expr, ctx)
    codegen.asm.instr("push rax")
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    codegen.emit_root_slot_updates(ctx.layout)
    rooted_runtime_arg_count = codegen.emit_runtime_call_arg_temp_roots(ctx.layout, runtime_ctor, 1, span=expr.span)
    codegen.asm.instr("pop rdi")
    codegen.emit_aligned_call(runtime_ctor)
    if rooted_runtime_arg_count > 0:
        codegen.emit_clear_runtime_call_arg_temp_roots(ctx.layout, rooted_runtime_arg_count)
    _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_callable_value_call(codegen: CodeGenerator, expr: CallableValueCallExpr, ctx: EmitContext) -> None:
    layout = ctx.layout
    call_argument_type_names = [infer_expression_type_name(arg) for arg in expr.args]
    reference_arg_indices = {
        index
        for index, type_name in enumerate(call_argument_type_names)
        if codegen_types.is_reference_type_name(type_name)
    }
    arg_locations = plan_sysv_arg_locations(call_argument_type_names)
    stack_arg_indices = [
        index
        for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
        if location_kind == "stack"
    ]
    temp_root_base = ctx.temp_root_depth[0]
    rooted_temp_arg_count = 0
    for arg_index in range(len(expr.args) - 1, -1, -1):
        emit_expr(codegen, expr.args[arg_index], ctx)
        codegen.asm.instr("push rax")
        if arg_index in reference_arg_indices:
            codegen.emit_temp_arg_root_from_rsp(layout, temp_root_base + rooted_temp_arg_count, 0, span=expr.span)
            rooted_temp_arg_count += 1
            ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count
    emit_expr(codegen, expr.callee, ctx)
    codegen.asm.instr("mov r11, rax")
    codegen.emit_root_slot_updates(layout)
    codegen.asm.instr("mov r10, rsp")
    for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
        arg_operand = stack_slot_operand("r10", arg_index * 8)
        if location_kind == "int_reg":
            codegen.asm.instr(f"mov {location_register}, {arg_operand}")
        elif location_kind == "float_reg":
            codegen.asm.instr(f"movq {location_register}, {arg_operand}")
    for arg_index in reversed(stack_arg_indices):
        codegen.asm.instr(f"mov rax, {stack_slot_operand('r10', arg_index * 8)}")
        codegen.asm.instr("push rax")
    codegen.emit_aligned_call("r11")
    cleanup_slot_count = len(expr.args) + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")
    if expr.type_name == "double":
        codegen.asm.instr("movq rax, xmm0")
    elif expr.type_name == "unit":
        codegen.asm.instr("mov rax, 0")
    if rooted_temp_arg_count > 0:
        codegen.emit_clear_temp_root_slots(layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base


def _emit_named_call(
    codegen: CodeGenerator,
    target_name: str,
    call_arguments: list[SemanticExpr],
    return_type_name: str,
    ctx: EmitContext,
) -> None:
    layout = ctx.layout
    call_argument_type_names = [infer_expression_type_name(arg) for arg in call_arguments]
    reference_arg_indices = {
        index
        for index, type_name in enumerate(call_argument_type_names)
        if codegen_types.is_reference_type_name(type_name)
    }
    arg_locations = plan_sysv_arg_locations(call_argument_type_names)
    stack_arg_indices = [
        index
        for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
        if location_kind == "stack"
    ]
    temp_root_base = ctx.temp_root_depth[0]
    is_runtime_call = codegen_symbols.is_runtime_call_name(target_name)
    if is_runtime_call:
        _emit_runtime_call_hooks_before(
            codegen,
            call_arguments[0].span.start.line if call_arguments else 0,
            call_arguments[0].span.start.column if call_arguments else 0,
            ctx,
        )
    rooted_temp_arg_count = 0
    for arg_index in range(len(call_arguments) - 1, -1, -1):
        emit_expr(codegen, call_arguments[arg_index], ctx)
        codegen.asm.instr("push rax")
        if arg_index in reference_arg_indices:
            codegen.emit_temp_arg_root_from_rsp(
                layout, temp_root_base + rooted_temp_arg_count, 0, span=call_arguments[arg_index].span
            )
            rooted_temp_arg_count += 1
            ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count
    codegen.emit_root_slot_updates(layout)
    codegen.asm.instr("mov r10, rsp")
    for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
        arg_operand = stack_slot_operand("r10", arg_index * 8)
        if location_kind == "int_reg":
            codegen.asm.instr(f"mov {location_register}, {arg_operand}")
        elif location_kind == "float_reg":
            codegen.asm.instr(f"movq {location_register}, {arg_operand}")
    for arg_index in reversed(stack_arg_indices):
        codegen.asm.instr(f"mov rax, {stack_slot_operand('r10', arg_index * 8)}")
        codegen.asm.instr("push rax")
    codegen.emit_aligned_call(target_name)
    cleanup_slot_count = len(call_arguments) + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")
    if return_type_name == "double":
        codegen.asm.instr("movq rax, xmm0")
    elif return_type_name == "unit":
        codegen.asm.instr("mov rax, 0")
    if rooted_temp_arg_count > 0:
        codegen.emit_clear_temp_root_slots(layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base
    if is_runtime_call:
        _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_index_read_expr(codegen: CodeGenerator, expr: IndexReadExpr, ctx: EmitContext) -> None:
    if expr.get_method is None:
        target_type = infer_expression_type_name(expr.target)
        element_type = codegen_types.array_element_type_name(target_type, span=expr.span)
        runtime_call = ARRAY_GET_RUNTIME_CALLS[codegen_types.array_element_runtime_kind(element_type)]
        _emit_named_call(codegen, runtime_call, [expr.target, expr.index], expr.result_type_name, ctx)
        return
    _emit_named_call(
        codegen, _method_label(expr.get_method, ctx), [expr.target, expr.index], expr.result_type_name, ctx
    )


def _emit_slice_read_expr(codegen: CodeGenerator, expr: SliceReadExpr, ctx: EmitContext) -> None:
    if expr.get_method is None:
        target_type = infer_expression_type_name(expr.target)
        element_type = codegen_types.array_element_type_name(target_type, span=expr.span)
        runtime_call = ARRAY_SLICE_RUNTIME_CALLS[codegen_types.array_element_runtime_kind(element_type)]
        _emit_named_call(codegen, runtime_call, [expr.target, expr.begin, expr.end], expr.result_type_name, ctx)
        return
    _emit_named_call(
        codegen, _method_label(expr.get_method, ctx), [expr.target, expr.begin, expr.end], expr.result_type_name, ctx
    )


def _emit_synthetic_expr(codegen: CodeGenerator, expr: SyntheticExpr, ctx: EmitContext) -> None:
    if expr.synthetic_id.kind != "string_literal_bytes":
        codegen_types.raise_codegen_error(
            f"synthetic expression codegen not implemented for kind '{expr.synthetic_id.kind}'", span=expr.span
        )
    label_and_len = ctx.string_literal_labels.get(expr.synthetic_id.name)
    if label_and_len is None:
        codegen_types.raise_codegen_error("missing string literal lowering metadata", span=expr.span)
    data_label, data_len = label_and_len
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    codegen.emit_root_slot_updates(ctx.layout)
    codegen.asm.instr(f"lea rdi, [rip + {data_label}]")
    codegen.asm.instr(f"mov rsi, {data_len}")
    codegen.emit_aligned_call("rt_array_from_bytes_u8")
    _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_unary_expr(codegen: CodeGenerator, expr: UnaryExprS, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.operand, ctx)
    operand_type_name = infer_expression_type_name(expr.operand)
    if expr.operator == "-" and operand_type_name == "double":
        emit_unary_negate_double(codegen.asm)
        return
    if emit_integer_unary_op(
        codegen.asm,
        operator=expr.operator,
        operand_type_name=operand_type_name,
        emit_bool_normalize=codegen.emit_bool_normalize,
    ):
        return
    codegen_types.raise_codegen_error(f"unary operator '{expr.operator}' is not supported", span=expr.span)


def _emit_binary_expr(codegen: CodeGenerator, expr: BinaryExprS, ctx: EmitContext) -> None:
    if _emit_logical_binary_expr(codegen, expr, ctx):
        return
    left_type_name = infer_expression_type_name(expr.left)
    right_type_name = infer_expression_type_name(expr.right)
    emit_expr(codegen, expr.left, ctx)
    codegen.asm.instr("push rax")
    emit_expr(codegen, expr.right, ctx)
    codegen.asm.instr("mov rcx, rax")
    codegen.asm.instr("pop rax")
    if left_type_name == "double" and right_type_name == "double":
        codegen.asm.instr("movq xmm1, rcx")
        codegen.asm.instr("movq xmm0, rax")
        if emit_double_binary_op(codegen.asm, expr.operator):
            return
        codegen_types.raise_codegen_error(
            f"binary operator '{expr.operator}' is not supported for double operands", span=expr.span
        )
    if emit_integer_binary_op(
        codegen.asm,
        operator=expr.operator,
        operand_type_name=left_type_name,
        fn_name=ctx.fn_name,
        label_counter=ctx.label_counter,
        next_label=codegen_symbols.next_label,
        runtime_panic_message_label=codegen.runtime_panic_message_label,
        emit_aligned_call=codegen.emit_aligned_call,
    ):
        if left_type_name == "u8" and expr.operator in {"+", "-", "*", "**", "/", "%", "&", "|", "^", "<<", ">>"}:
            codegen.asm.instr("and rax, 255")
        return
    codegen_types.raise_codegen_error(f"binary operator '{expr.operator}' is not supported", span=expr.span)


def _emit_logical_binary_expr(codegen: CodeGenerator, expr: BinaryExprS, ctx: EmitContext) -> bool:
    if expr.operator not in ("&&", "||"):
        return False
    branch_id = ctx.label_counter[0]
    ctx.label_counter[0] += 1
    rhs_label = f".L{ctx.fn_name}_logic_rhs_{branch_id}"
    done_label = f".L{ctx.fn_name}_logic_done_{branch_id}"
    emit_expr(codegen, expr.left, ctx)
    codegen.emit_bool_normalize()
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
    codegen.emit_bool_normalize()
    codegen.asm.label(done_label)
    return True


def _emit_runtime_call_hooks_before(codegen: CodeGenerator, line: int, column: int, ctx: EmitContext) -> None:
    codegen.emit_runtime_call_hook(
        fn_name=ctx.fn_name, phase="before", label_counter=ctx.label_counter, line=line, column=column
    )


def _emit_runtime_call_hooks_after(codegen: CodeGenerator, ctx: EmitContext) -> None:
    codegen.emit_runtime_call_hook(fn_name=ctx.fn_name, phase="after", label_counter=ctx.label_counter)


def _method_label(method_id: MethodId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.method_labels_by_id.get(method_id)
    if label is None:
        raise ValueError(f"Missing method label for {method_id}")
    return label


def _constructor_label(class_name: str) -> str:
    return codegen_symbols.mangle_constructor_symbol(class_name)


def _resolve_field_offset(ctx: EmitContext, receiver_type_name: str, field_name: str) -> int | None:
    if "::" in receiver_type_name:
        _owner_dotted, class_name = receiver_type_name.split("::", 1)
    else:
        class_name = receiver_type_name

    matches = [
        offset
        for (class_id, candidate_field_name), offset in ctx.declaration_tables.class_field_offsets_by_id.items()
        if candidate_field_name == field_name and class_id.name == class_name
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Ambiguous semantic field offset resolution for '{receiver_type_name}.{field_name}'")
    return matches[0]
