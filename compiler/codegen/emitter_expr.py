from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from compiler.common.type_names import *
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.abi.sysv import plan_sysv_arg_locations
from compiler.codegen.asm import offset_operand, stack_slot_operand
from compiler.codegen.abi.runtime import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_LEN_RUNTIME_CALL,
    DOUBLE_TO_I64_RUNTIME_CALL,
    DOUBLE_TO_U64_RUNTIME_CALL,
    DOUBLE_TO_U8_RUNTIME_CALL,
    U64_TO_DOUBLE_RUNTIME_CALL,
)
from compiler.codegen.model import FunctionLayout
from compiler.codegen.ops_float import emit_double_binary_op, emit_unary_negate_double
from compiler.codegen.ops_int import emit_integer_binary_op, emit_integer_unary_op
from compiler.codegen.runtime_calls import runtime_dispatch_call_name
from compiler.resolver import ModulePath
from compiler.semantic.ir import *
from compiler.semantic.lowered_ir import LoweredSemanticFunctionLike
from compiler.semantic.operations import (
    BinaryOpFlavor,
    BinaryOpKind,
    CastSemanticsKind,
    TypeTestSemanticsKind,
    UnaryOpFlavor,
    UnaryOpKind,
    binary_op_text,
    binary_op_uses_u8_mask,
    unary_op_text,
)
from compiler.semantic.symbols import InterfaceMethodId, MethodId
from compiler.semantic.types import (
    semantic_type_array_element,
    semantic_type_canonical_name,
    semantic_type_display_name,
    semantic_type_is_array,
)

if TYPE_CHECKING:
    from compiler.codegen.generator import CodeGenerator
    from compiler.codegen.program_generator import DeclarationTables


@dataclass
class EmitContext:
    layout: FunctionLayout
    fn_name: str
    current_module_path: ModulePath
    owner: SemanticFunctionLike | LoweredSemanticFunctionLike | None
    label_counter: list[int]
    string_literal_labels: dict[str, tuple[str, int]]
    temp_root_depth: list[int]
    declaration_tables: DeclarationTables


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
    if isinstance(expr, TypeTestExprS):
        _emit_type_test_expr(codegen, expr, ctx)
        return
    if isinstance(expr, ArrayCtorExprS):
        _emit_array_ctor_expr(codegen, expr, ctx)
        return
    if isinstance(expr, CallExprS):
        _emit_call_expr(codegen, expr, ctx)
        return
    if isinstance(expr, ArrayLenExpr):
        _emit_named_call(codegen, ARRAY_LEN_RUNTIME_CALL, [expr.target], TYPE_NAME_U64, ctx)
        return
    if isinstance(expr, IndexReadExpr):
        _emit_index_read_expr(codegen, expr, ctx)
        return
    if isinstance(expr, SliceReadExpr):
        _emit_slice_read_expr(codegen, expr, ctx)
        return
    if isinstance(expr, StringLiteralBytesExpr):
        _emit_string_literal_bytes_expr(codegen, expr, ctx)
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
    offset = ctx.layout.local_slot_offsets.get(expr.local_id)
    if offset is None:
        local_label = str(expr.local_id) if ctx.owner is None else local_display_name_for_owner(ctx.owner, expr.local_id)
        codegen_types.raise_codegen_error(
            f"identifier '{local_label}' is not materialized in stack layout", span=expr.span
        )
    codegen.asm.instr(f"mov rax, {offset_operand(offset)}")


def _emit_method_ref_expr(codegen: CodeGenerator, expr: MethodRefExpr, ctx: EmitContext) -> None:
    if expr.receiver is not None:
        codegen_types.raise_codegen_error("bound instance method references are not implemented", span=expr.span)
    codegen.asm.instr(f"lea rax, [rip + {_method_label(expr.method_id, ctx)}]")


def _emit_literal_expr(codegen: CodeGenerator, expr: LiteralExprS) -> None:
    constant = expr.constant
    if isinstance(constant, BoolConstant):
        codegen.asm.instr(f"mov rax, {1 if constant.value else 0}")
        return
    if isinstance(constant, FloatConstant):
        codegen.asm.instr(f"mov rax, 0x{codegen_types.double_value_bits(constant.value):016x}")
        return
    if isinstance(constant, CharConstant):
        codegen.asm.instr(f"mov rax, {constant.value}")
        return
    if isinstance(constant, IntConstant):
        codegen.asm.instr(f"mov rax, {constant.value}")
        return
    codegen_types.raise_codegen_error(
        f"literal codegen not implemented for {type(constant).__name__}", span=expr.span
    )


def _emit_field_read_expr(codegen: CodeGenerator, expr: FieldReadExpr, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.access.receiver, ctx)
    field_offset = ctx.declaration_tables.class_field_offset(expr.owner_class_id, expr.field_name)
    if field_offset is None:
        codegen_types.raise_codegen_error(
            f"field access codegen missing field '{expr.field_name}' on class '{expr.owner_class_id.name}'",
            span=expr.span,
        )
    codegen.asm.instr(f"mov rax, qword ptr [rax + {field_offset}]")


def _emit_reference_type_runtime_check(
    codegen: CodeGenerator,
    operand: SemanticExpr,
    target_type_ref,
    interface_runtime_call: str,
    class_runtime_call: str,
    ctx: EmitContext,
) -> None:
    emit_expr(codegen, operand, ctx)
    interface_descriptor_symbol = ctx.declaration_tables.interface_descriptor_symbol_for_type_ref(target_type_ref)
    codegen.asm.instr("push rax")
    _emit_runtime_call_hooks_before(codegen, operand.span.start.line, operand.span.start.column, ctx)
    codegen.asm.instr("pop rax")
    codegen.asm.instr("mov rdi, rax")
    if interface_descriptor_symbol is not None:
        codegen.asm.instr(f"lea rsi, [rip + {interface_descriptor_symbol}]")
        codegen.emit_aligned_call(interface_runtime_call)
    else:
        codegen.asm.instr(
            f"lea rsi, [rip + {codegen_symbols.mangle_type_symbol(semantic_type_canonical_name(target_type_ref))}]"
        )
        codegen.emit_aligned_call(class_runtime_call)
    _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_cast_expr(codegen: CodeGenerator, expr: CastExprS, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.operand, ctx)
    source_type = semantic_type_canonical_name(expression_type_ref(expr.operand))
    target_type = semantic_type_canonical_name(expr.target_type_ref)
    if expr.cast_kind == CastSemanticsKind.IDENTITY:
        return
    if expr.cast_kind == CastSemanticsKind.REFERENCE_COMPATIBILITY:
        if target_type == TYPE_NAME_OBJ and source_type != TYPE_NAME_NULL and codegen_types.is_reference_type_name(source_type):
            return
        if semantic_type_is_array(expr.target_type_ref) and source_type == TYPE_NAME_OBJ:
            element_type = semantic_type_array_element(expr.target_type_ref)
            array_kind_by_element_type = {
                TYPE_NAME_I64: 1,
                TYPE_NAME_U64: 2,
                TYPE_NAME_U8: 3,
                TYPE_NAME_BOOL: 4,
                TYPE_NAME_DOUBLE: 5,
            }
            expected_kind = array_kind_by_element_type.get(semantic_type_canonical_name(element_type), 6)
            codegen.asm.instr("push rax")
            _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
            codegen.asm.instr("pop rax")
            codegen.asm.instr("mov rdi, rax")
            codegen.asm.instr(f"mov rsi, {expected_kind}")
            codegen.emit_aligned_call("rt_checked_cast_array_kind")
            _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if codegen_types.is_reference_type_ref(expr.target_type_ref):
            _emit_reference_type_runtime_check(
                codegen,
                expr.operand,
                expr.target_type_ref,
                "rt_checked_cast_interface",
                "rt_checked_cast",
                ctx,
            )
            return

    if expr.cast_kind == CastSemanticsKind.TO_DOUBLE:
        if source_type == TYPE_NAME_U64:
            codegen.asm.instr("push rax")
            _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
            codegen.asm.instr("pop rax")
            codegen.asm.instr("mov rdi, rax")
            codegen.emit_aligned_call(U64_TO_DOUBLE_RUNTIME_CALL)
            _emit_runtime_call_hooks_after(codegen, ctx)
            codegen.asm.instr("movq rax, xmm0")
            return
        codegen.asm.instr("cvtsi2sd xmm0, rax")
        codegen.asm.instr("movq rax, xmm0")
        return

    if expr.cast_kind == CastSemanticsKind.TO_INTEGER:
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_I64:
            codegen.asm.instr("push rax")
            _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
            codegen.asm.instr("pop rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_I64_RUNTIME_CALL)
            _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_U64:
            codegen.asm.instr("push rax")
            _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
            codegen.asm.instr("pop rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_U64_RUNTIME_CALL)
            _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_U8:
            codegen.asm.instr("push rax")
            _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
            codegen.asm.instr("pop rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_U8_RUNTIME_CALL)
            _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if target_type == TYPE_NAME_U8:
            codegen.asm.instr("and rax, 255")
        return

    if expr.cast_kind == CastSemanticsKind.TO_BOOL:
        if source_type == TYPE_NAME_DOUBLE:
            codegen.asm.instr("movq xmm0, rax")
            codegen.asm.instr("xorpd xmm1, xmm1")
            codegen.asm.instr("ucomisd xmm0, xmm1")
            codegen.asm.instr("setne al")
            codegen.asm.instr("setp dl")
            codegen.asm.instr("or al, dl")
            codegen.asm.instr("movzx rax, al")
            return
        codegen.emit_bool_normalize()
        return


def _emit_type_test_expr(codegen: CodeGenerator, expr: TypeTestExprS, ctx: EmitContext) -> None:
    if expr.test_kind not in {TypeTestSemanticsKind.CLASS_COMPATIBILITY, TypeTestSemanticsKind.INTERFACE_COMPATIBILITY}:
        codegen_types.raise_codegen_error(
            f"type test codegen requires reference target type, got '{semantic_type_display_name(expr.target_type_ref)}'",
            span=expr.span,
        )
    _emit_reference_type_runtime_check(
        codegen,
        expr.operand,
        expr.target_type_ref,
        "rt_is_instance_of_interface",
        "rt_is_instance_of_type",
        ctx,
    )
    codegen.emit_bool_normalize()


def _emit_array_ctor_expr(codegen: CodeGenerator, expr: ArrayCtorExprS, ctx: EmitContext) -> None:
    runtime_kind = codegen_types.array_element_runtime_kind_for_type_ref(expr.element_type_ref)
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


def _emit_call_expr(codegen: CodeGenerator, expr: CallExprS, ctx: EmitContext) -> None:
    target = expr.target
    if isinstance(target, FunctionCallTarget):
        _emit_named_call(codegen, target.function_id.name, expr.args, expr.type_ref, ctx)
        return
    if isinstance(target, StaticMethodCallTarget):
        _emit_named_call(codegen, _method_label(target.method_id, ctx), expr.args, expr.type_ref, ctx)
        return
    if isinstance(target, InstanceMethodCallTarget):
        _emit_named_call(codegen, _method_label(target.method_id, ctx), [target.access.receiver, *expr.args], expr.type_ref, ctx)
        return
    if isinstance(target, InterfaceMethodCallTarget):
        _emit_interface_method_call(codegen, expr, target, ctx)
        return
    if isinstance(target, ConstructorCallTarget):
        _emit_named_call(codegen, _constructor_label(target.constructor_id, ctx), expr.args, expr.type_ref, ctx)
        return
    _emit_callable_value_call(codegen, expr, target.callee, ctx)


def _emit_callable_value_call(
    codegen: CodeGenerator, expr: CallExprS, callee: SemanticExpr, ctx: EmitContext
) -> None:
    _emit_call_sequence(
        codegen,
        call_arguments=expr.args,
        return_type_ref=expr.type_ref,
        ctx=ctx,
        callee_expr=callee,
        temp_root_spans=[expr.span] * len(expr.args),
    )


def _emit_interface_method_call(
    codegen: CodeGenerator, expr: CallExprS, target: InterfaceMethodCallTarget, ctx: EmitContext
) -> None:
    descriptor_symbol = ctx.declaration_tables.interface_descriptor_symbol(target.interface_id)
    if descriptor_symbol is None:
        codegen_types.raise_codegen_error(
            f"missing interface descriptor symbol for {target.interface_id}", span=expr.span
        )

    method_slot = _interface_method_slot(target.method_id, ctx)
    temp_root_base = ctx.temp_root_depth[0]
    receiver_temp_index = temp_root_base
    rooted_temp_arg_count = 1

    emit_expr(codegen, target.access.receiver, ctx)
    codegen.emit_temp_root_slot_store(ctx.layout, receiver_temp_index, "rax", span=expr.span)
    ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count
    codegen.asm.instr(f"mov rax, {offset_operand(ctx.layout.temp_root_slot_offsets[receiver_temp_index])}")

    codegen.asm.instr("push rax")
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    codegen.emit_root_slot_updates(ctx.layout)
    codegen.emit_temp_arg_root_from_rsp(ctx.layout, receiver_temp_index, 0, span=expr.span)
    codegen.asm.instr("mov rdi, qword ptr [rsp]")
    codegen.asm.instr(f"lea rsi, [rip + {descriptor_symbol}]")
    codegen.asm.instr(f"mov edx, {method_slot}")
    codegen.emit_aligned_call("rt_lookup_interface_method")
    codegen.asm.instr("add rsp, 8")
    _emit_runtime_call_hooks_after(codegen, ctx)

    codegen.asm.instr("push rax")

    call_arguments = [target.access.receiver, *expr.args]
    call_argument_type_names = [_canonical_expr_type_name(arg) for arg in call_arguments]
    reference_arg_indices = {
        index
        for index, type_name in enumerate(call_argument_type_names)
        if codegen_types.is_reference_type_name(type_name)
    }

    for arg_index in range(len(expr.args) - 1, -1, -1):
        arg = expr.args[arg_index]
        emit_expr(codegen, arg, ctx)
        codegen.asm.instr("push rax")
        call_arg_index = arg_index + 1
        if call_arg_index in reference_arg_indices:
            codegen.emit_temp_arg_root_from_rsp(
                ctx.layout,
                temp_root_base + rooted_temp_arg_count,
                0,
                span=arg.span,
            )
            rooted_temp_arg_count += 1
            ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count

    codegen.asm.instr(f"mov rax, {offset_operand(ctx.layout.temp_root_slot_offsets[receiver_temp_index])}")
    codegen.asm.instr("push rax")

    arg_locations = plan_sysv_arg_locations(call_argument_type_names)
    stack_arg_indices = [
        index
        for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
        if location_kind == "stack"
    ]

    codegen.emit_root_slot_updates(ctx.layout)
    codegen.asm.instr("mov r10, rsp")
    codegen.asm.instr(f"mov r11, {stack_slot_operand('r10', len(call_arguments) * 8)}")
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

    cleanup_slot_count = len(call_arguments) + len(stack_arg_indices) + 1
    if cleanup_slot_count > 0:
        codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")
    return_type_name = semantic_type_canonical_name(expr.type_ref)
    if return_type_name == TYPE_NAME_DOUBLE:
        codegen.asm.instr("movq rax, xmm0")
    elif return_type_name == TYPE_NAME_UNIT:
        codegen.asm.instr("mov rax, 0")

    codegen.emit_clear_temp_root_slots(ctx.layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base


def _emit_named_call(
    codegen: CodeGenerator,
    target_name: str,
    call_arguments: list[SemanticExpr],
    return_type_ref: SemanticTypeRef | str,
    ctx: EmitContext,
) -> None:
    runtime_hook_span = call_arguments[0].span if codegen_symbols.is_runtime_call_name(target_name) and call_arguments else None
    _emit_call_sequence(
        codegen,
        call_arguments=call_arguments,
        return_type_ref=return_type_ref,
        ctx=ctx,
        target_name=target_name,
        temp_root_spans=[arg.span for arg in call_arguments],
        runtime_hook_span=runtime_hook_span,
    )


def _emit_call_sequence(
    codegen: CodeGenerator,
    call_arguments: list[SemanticExpr],
    return_type_ref: SemanticTypeRef | str,
    ctx: EmitContext,
    *,
    target_name: str | None = None,
    callee_expr: SemanticExpr | None = None,
    temp_root_spans: list[object | None],
    runtime_hook_span: object | None = None,
) -> None:
    if (target_name is None) == (callee_expr is None):
        raise ValueError("call emission requires exactly one of target_name or callee_expr")

    layout = ctx.layout
    call_argument_type_names = [_canonical_expr_type_name(arg) for arg in call_arguments]
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
    if runtime_hook_span is not None:
        _emit_runtime_call_hooks_before(
            codegen,
            runtime_hook_span.start.line,
            runtime_hook_span.start.column,
            ctx,
        )
    rooted_temp_arg_count = 0
    for arg_index in range(len(call_arguments) - 1, -1, -1):
        emit_expr(codegen, call_arguments[arg_index], ctx)
        codegen.asm.instr("push rax")
        if arg_index in reference_arg_indices:
            codegen.emit_temp_arg_root_from_rsp(
                layout, temp_root_base + rooted_temp_arg_count, 0, span=temp_root_spans[arg_index]
            )
            rooted_temp_arg_count += 1
            ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count
    call_target = target_name
    if callee_expr is not None:
        emit_expr(codegen, callee_expr, ctx)
        codegen.asm.instr("mov r11, rax")
        call_target = "r11"
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
    codegen.emit_aligned_call(call_target)
    cleanup_slot_count = len(call_arguments) + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.asm.instr(f"add rsp, {cleanup_slot_count * 8}")
    return_type_name = (
        return_type_ref if isinstance(return_type_ref, str) else semantic_type_canonical_name(return_type_ref)
    )
    if return_type_name == TYPE_NAME_DOUBLE:
        codegen.asm.instr("movq rax, xmm0")
    elif return_type_name == TYPE_NAME_UNIT:
        codegen.asm.instr("mov rax, 0")
    if rooted_temp_arg_count > 0:
        codegen.emit_clear_temp_root_slots(layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base
    if runtime_hook_span is not None:
        _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_index_read_expr(codegen: CodeGenerator, expr: IndexReadExpr, ctx: EmitContext) -> None:
    _emit_named_call(codegen, _dispatch_target_name(expr.dispatch, ctx), [expr.target, expr.index], expr.type_ref, ctx)


def _emit_slice_read_expr(codegen: CodeGenerator, expr: SliceReadExpr, ctx: EmitContext) -> None:
    _emit_named_call(
        codegen, _dispatch_target_name(expr.dispatch, ctx), [expr.target, expr.begin, expr.end], expr.type_ref, ctx
    )


def _emit_string_literal_bytes_expr(codegen: CodeGenerator, expr: StringLiteralBytesExpr, ctx: EmitContext) -> None:
    label_and_len = ctx.string_literal_labels.get(expr.literal_text)
    if label_and_len is None:
        codegen_types.raise_codegen_error("missing string literal lowering metadata", span=expr.span)
    data_label, data_len = label_and_len
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    codegen.emit_root_slot_updates(ctx.layout)
    codegen.asm.instr(f"lea rdi, [rip + {data_label}]")
    codegen.asm.instr(f"mov rsi, {data_len}")
    codegen.emit_aligned_call(ARRAY_FROM_BYTES_U8_RUNTIME_CALL)
    _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_unary_expr(codegen: CodeGenerator, expr: UnaryExprS, ctx: EmitContext) -> None:
    emit_expr(codegen, expr.operand, ctx)
    operand_type_name = _canonical_expr_type_name(expr.operand)
    if expr.op.flavor == UnaryOpFlavor.FLOAT and expr.op.kind == UnaryOpKind.NEGATE:
        emit_unary_negate_double(codegen.asm)
        return
    if emit_integer_unary_op(
        codegen.asm,
        op_kind=expr.op.kind,
        operand_type_name=operand_type_name,
        emit_bool_normalize=codegen.emit_bool_normalize,
    ):
        return
    codegen_types.raise_codegen_error(
        f"unary operator '{unary_op_text(expr.op)}' is not supported", span=expr.span
    )


def _emit_binary_expr(codegen: CodeGenerator, expr: BinaryExprS, ctx: EmitContext) -> None:
    if _emit_logical_binary_expr(codegen, expr, ctx):
        return
    left_type_name = _canonical_expr_type_name(expr.left)
    right_type_name = _canonical_expr_type_name(expr.right)
    emit_expr(codegen, expr.left, ctx)
    codegen.asm.instr("push rax")
    emit_expr(codegen, expr.right, ctx)
    codegen.asm.instr("mov rcx, rax")
    codegen.asm.instr("pop rax")
    if expr.op.flavor in {BinaryOpFlavor.FLOAT, BinaryOpFlavor.FLOAT_COMPARISON}:
        codegen.asm.instr("movq xmm1, rcx")
        codegen.asm.instr("movq xmm0, rax")
        if emit_double_binary_op(codegen.asm, expr.op.kind):
            return
        codegen_types.raise_codegen_error(
            f"binary operator '{binary_op_text(expr.op)}' is not supported for double operands", span=expr.span
        )
    if emit_integer_binary_op(
        codegen.asm,
        op_kind=expr.op.kind,
        operand_type_name=left_type_name,
        fn_name=ctx.fn_name,
        label_counter=ctx.label_counter,
        next_label=codegen_symbols.next_label,
        runtime_panic_message_label=codegen.runtime_panic_message_label,
        emit_aligned_call=codegen.emit_aligned_call,
    ):
        if left_type_name == TYPE_NAME_U8 and binary_op_uses_u8_mask(expr.op.kind):
            codegen.asm.instr("and rax, 255")
        return
    codegen_types.raise_codegen_error(
        f"binary operator '{binary_op_text(expr.op)}' is not supported", span=expr.span
    )


def _emit_logical_binary_expr(codegen: CodeGenerator, expr: BinaryExprS, ctx: EmitContext) -> bool:
    if expr.op.kind not in (BinaryOpKind.LOGICAL_AND, BinaryOpKind.LOGICAL_OR):
        return False
    branch_id = ctx.label_counter[0]
    ctx.label_counter[0] += 1
    rhs_label = f".L{ctx.fn_name}_logic_rhs_{branch_id}"
    done_label = f".L{ctx.fn_name}_logic_done_{branch_id}"
    emit_expr(codegen, expr.left, ctx)
    codegen.emit_bool_normalize()
    codegen.asm.instr("cmp rax, 0")
    if expr.op.kind == BinaryOpKind.LOGICAL_AND:
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


def _canonical_expr_type_name(expr: SemanticExpr) -> str:
    return semantic_type_canonical_name(expression_type_ref(expr))


def _emit_runtime_call_hooks_after(codegen: CodeGenerator, ctx: EmitContext) -> None:
    codegen.emit_runtime_call_hook(fn_name=ctx.fn_name, phase="after", label_counter=ctx.label_counter)


def _method_label(method_id: MethodId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.method_label(method_id)
    if label is None:
        raise ValueError(f"Missing method label for {method_id}")
    return label


def _dispatch_target_name(dispatch: SemanticDispatch, ctx: EmitContext) -> str:
    if isinstance(dispatch, RuntimeDispatch):
        return runtime_dispatch_call_name(dispatch)
    return _method_label(dispatch.method_id, ctx)


def _interface_method_slot(method_id: InterfaceMethodId, ctx: EmitContext) -> int:
    slot = ctx.declaration_tables.interface_method_slot(method_id)
    if slot is None:
        raise ValueError(f"Missing interface method slot for {method_id}")
    return slot


def _constructor_label(constructor_id: ConstructorId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.constructor_label(constructor_id)
    if label is None:
        raise ValueError(f"Missing constructor label for {constructor_id}")
    return label
