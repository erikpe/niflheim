from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from compiler.common.type_names import *
import compiler.codegen.symbols as codegen_symbols
import compiler.codegen.types as codegen_types

from compiler.codegen.abi.array import ARRAY_API_NULL_PANIC_MESSAGE, array_data_index_address, array_length_operand
from compiler.codegen.abi.object import (
    class_vtable_entry_operand,
    class_vtable_operand,
    interface_debug_name_operand,
    interface_method_entry_operand,
    interface_table_entry_operand,
    interface_tables_operand,
    object_type_operand,
    type_debug_name_operand,
)
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
    RuntimeCallMetadata,
    runtime_call_metadata,
)
from compiler.codegen.model import FunctionLayout
from compiler.codegen.root_liveness import NamedRootLiveness
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
    call_scratch_depth: list[int]
    declaration_tables: DeclarationTables
    named_root_liveness: NamedRootLiveness | None = None
    tracked_named_root_local_ids: frozenset[LocalId] = frozenset()
    dirty_named_root_local_ids: set[LocalId] | None = None
    known_cleared_named_root_local_ids: set[LocalId] | None = None

    def snapshot_dirty_named_roots(self) -> set[LocalId]:
        if self.dirty_named_root_local_ids is None:
            return set()
        return set(self.dirty_named_root_local_ids)

    def restore_dirty_named_roots(self, dirty_local_ids: set[LocalId]) -> None:
        if self.dirty_named_root_local_ids is None:
            return
        self.dirty_named_root_local_ids.clear()
        self.dirty_named_root_local_ids.update(
            local_id for local_id in dirty_local_ids if local_id in self.tracked_named_root_local_ids
        )

    def snapshot_known_cleared_named_roots(self) -> set[LocalId]:
        if self.known_cleared_named_root_local_ids is None:
            return set()
        return set(self.known_cleared_named_root_local_ids)

    def restore_known_cleared_named_roots(self, cleared_local_ids: set[LocalId]) -> None:
        if self.known_cleared_named_root_local_ids is None:
            return
        self.known_cleared_named_root_local_ids.clear()
        self.known_cleared_named_root_local_ids.update(
            local_id for local_id in cleared_local_ids if local_id in self.tracked_named_root_local_ids
        )

    def merge_dirty_named_roots(self, *dirty_states: set[LocalId]) -> None:
        merged: set[LocalId] = set()
        for dirty_state in dirty_states:
            merged.update(dirty_state)
        self.restore_dirty_named_roots(merged)

    def intersect_known_cleared_named_roots(self, *cleared_states: set[LocalId]) -> None:
        if self.known_cleared_named_root_local_ids is None:
            return
        intersected = set(self.tracked_named_root_local_ids)
        for cleared_state in cleared_states:
            intersected.intersection_update(cleared_state)
        self.restore_known_cleared_named_roots(intersected)

    def invalidate_all_named_roots(self) -> None:
        if self.dirty_named_root_local_ids is None:
            return
        self.dirty_named_root_local_ids.clear()
        self.dirty_named_root_local_ids.update(self.tracked_named_root_local_ids)
        if self.known_cleared_named_root_local_ids is not None:
            self.known_cleared_named_root_local_ids.clear()

    def mark_named_root_dirty(self, local_id: LocalId) -> None:
        if self.dirty_named_root_local_ids is None or local_id not in self.tracked_named_root_local_ids:
            return
        self.dirty_named_root_local_ids.add(local_id)

    def mark_named_roots_clean(self, local_ids: Iterable[LocalId]) -> None:
        if self.dirty_named_root_local_ids is None:
            return
        self.dirty_named_root_local_ids.difference_update(local_ids)

    def mark_named_roots_synced(self, local_ids: Iterable[LocalId]) -> None:
        tracked_local_ids = {local_id for local_id in local_ids if local_id in self.tracked_named_root_local_ids}
        self.mark_named_roots_clean(tracked_local_ids)
        if self.known_cleared_named_root_local_ids is not None:
            self.known_cleared_named_root_local_ids.difference_update(tracked_local_ids)

    def mark_named_roots_cleared(self, local_ids: Iterable[LocalId]) -> None:
        tracked_local_ids = {local_id for local_id in local_ids if local_id in self.tracked_named_root_local_ids}
        self.mark_named_roots_clean(tracked_local_ids)
        if self.known_cleared_named_root_local_ids is not None:
            self.known_cleared_named_root_local_ids.update(tracked_local_ids)


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
        _emit_array_len_expr(codegen, expr, ctx)
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


def _emit_class_reference_type_runtime_check(
    codegen: CodeGenerator,
    operand: SemanticExpr,
    target_type_ref,
    class_runtime_call: str,
    ctx: EmitContext,
) -> None:
    emit_expr(codegen, operand, ctx)
    if _runtime_call_emits_safepoint_hooks(class_runtime_call):
        codegen.emit_push("rax")
        _emit_runtime_call_hooks_before(codegen, operand.span.start.line, operand.span.start.column, ctx)
        codegen.emit_pop("rax")
    codegen.asm.instr("mov rdi, rax")
    codegen.asm.instr(
        f"lea rsi, [rip + {codegen_symbols.mangle_type_symbol(semantic_type_canonical_name(target_type_ref))}]"
    )
    codegen.emit_aligned_call(class_runtime_call)
    if _runtime_call_emits_safepoint_hooks(class_runtime_call):
        _emit_runtime_call_hooks_after(codegen, ctx)


def _interface_descriptor_symbol(target_type_ref, ctx: EmitContext, *, span) -> str:
    interface_descriptor_symbol = ctx.declaration_tables.interface_descriptor_symbol_for_type_ref(target_type_ref)
    if interface_descriptor_symbol is None:
        codegen_types.raise_codegen_error(
            f"missing interface descriptor metadata for '{semantic_type_display_name(target_type_ref)}'",
            span=span,
        )
    return interface_descriptor_symbol


def _emit_inline_interface_cast(codegen: CodeGenerator, operand: SemanticExpr, target_type_ref, ctx: EmitContext) -> None:
    interface_id = target_type_ref.interface_id
    if interface_id is None:
        codegen_types.raise_codegen_error(
            f"inline interface cast requires interface target, got '{semantic_type_display_name(target_type_ref)}'",
            span=operand.span,
        )

    emit_expr(codegen, operand, ctx)
    cast_done_label = codegen_symbols.next_label(ctx.fn_name, "interface_cast_done", ctx.label_counter)
    cast_fail_label = codegen_symbols.next_label(ctx.fn_name, "interface_cast_fail", ctx.label_counter)
    interface_slot = _interface_slot(interface_id, ctx)
    interface_descriptor_symbol = _interface_descriptor_symbol(target_type_ref, ctx, span=operand.span)

    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"je {cast_done_label}")
    codegen.asm.instr(f"mov rcx, {object_type_operand('rax')}")
    codegen.asm.instr(f"mov rcx, {interface_tables_operand('rcx')}")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr(f"je {cast_fail_label}")
    codegen.asm.instr(f"mov rcx, {interface_table_entry_operand('rcx', interface_slot)}")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr(f"jne {cast_done_label}")
    codegen.asm.label(cast_fail_label)
    codegen.asm.instr(f"mov rcx, {object_type_operand('rax')}")
    codegen.asm.instr(f"mov rdi, {type_debug_name_operand('rcx')}")
    codegen.asm.instr(f"lea rsi, [rip + {interface_descriptor_symbol}]")
    codegen.asm.instr(f"mov rsi, {interface_debug_name_operand('rsi')}")
    codegen.emit_aligned_call("rt_panic_bad_cast")
    codegen.asm.label(cast_done_label)


def _emit_inline_interface_type_test(
    codegen: CodeGenerator,
    operand: SemanticExpr,
    target_type_ref,
    ctx: EmitContext,
) -> None:
    interface_id = target_type_ref.interface_id
    if interface_id is None:
        codegen_types.raise_codegen_error(
            f"inline interface type test requires interface target, got '{semantic_type_display_name(target_type_ref)}'",
            span=operand.span,
        )

    emit_expr(codegen, operand, ctx)
    type_test_false_label = codegen_symbols.next_label(ctx.fn_name, "interface_type_test_false", ctx.label_counter)
    type_test_done_label = codegen_symbols.next_label(ctx.fn_name, "interface_type_test_done", ctx.label_counter)
    interface_slot = _interface_slot(interface_id, ctx)

    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"je {type_test_false_label}")
    codegen.asm.instr(f"mov rcx, {object_type_operand('rax')}")
    codegen.asm.instr(f"mov rcx, {interface_tables_operand('rcx')}")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr(f"je {type_test_false_label}")
    codegen.asm.instr(f"mov rcx, {interface_table_entry_operand('rcx', interface_slot)}")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr("setne al")
    codegen.asm.instr("movzx rax, al")
    codegen.asm.instr(f"jmp {type_test_done_label}")
    codegen.asm.label(type_test_false_label)
    codegen.asm.instr("mov rax, 0")
    codegen.asm.label(type_test_done_label)


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
            if _runtime_call_emits_safepoint_hooks("rt_checked_cast_array_kind"):
                codegen.emit_push("rax")
                _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
                codegen.emit_pop("rax")
            codegen.asm.instr("mov rdi, rax")
            codegen.asm.instr(f"mov rsi, {expected_kind}")
            codegen.emit_aligned_call("rt_checked_cast_array_kind")
            if _runtime_call_emits_safepoint_hooks("rt_checked_cast_array_kind"):
                _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if codegen_types.is_reference_type_ref(expr.target_type_ref):
            if expr.target_type_ref.interface_id is not None:
                _emit_inline_interface_cast(codegen, expr.operand, expr.target_type_ref, ctx)
            else:
                _emit_class_reference_type_runtime_check(
                    codegen,
                    expr.operand,
                    expr.target_type_ref,
                    "rt_checked_cast",
                    ctx,
                )
            return

    if expr.cast_kind == CastSemanticsKind.TO_DOUBLE:
        if source_type == TYPE_NAME_U64:
            if _runtime_call_emits_safepoint_hooks(U64_TO_DOUBLE_RUNTIME_CALL):
                codegen.emit_push("rax")
                _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
                codegen.emit_pop("rax")
            codegen.asm.instr("mov rdi, rax")
            codegen.emit_aligned_call(U64_TO_DOUBLE_RUNTIME_CALL)
            if _runtime_call_emits_safepoint_hooks(U64_TO_DOUBLE_RUNTIME_CALL):
                _emit_runtime_call_hooks_after(codegen, ctx)
            codegen.asm.instr("movq rax, xmm0")
            return
        codegen.asm.instr("cvtsi2sd xmm0, rax")
        codegen.asm.instr("movq rax, xmm0")
        return

    if expr.cast_kind == CastSemanticsKind.TO_INTEGER:
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_I64:
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_I64_RUNTIME_CALL):
                codegen.emit_push("rax")
                _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
                codegen.emit_pop("rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_I64_RUNTIME_CALL)
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_I64_RUNTIME_CALL):
                _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_U64:
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_U64_RUNTIME_CALL):
                codegen.emit_push("rax")
                _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
                codegen.emit_pop("rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_U64_RUNTIME_CALL)
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_U64_RUNTIME_CALL):
                _emit_runtime_call_hooks_after(codegen, ctx)
            return
        if source_type == TYPE_NAME_DOUBLE and target_type == TYPE_NAME_U8:
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_U8_RUNTIME_CALL):
                codegen.emit_push("rax")
                _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
                codegen.emit_pop("rax")
            codegen.asm.instr("movq xmm0, rax")
            codegen.emit_aligned_call(DOUBLE_TO_U8_RUNTIME_CALL)
            if _runtime_call_emits_safepoint_hooks(DOUBLE_TO_U8_RUNTIME_CALL):
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
    if expr.test_kind == TypeTestSemanticsKind.INTERFACE_COMPATIBILITY:
        _emit_inline_interface_type_test(codegen, expr.operand, expr.target_type_ref, ctx)
        return
    _emit_class_reference_type_runtime_check(
        codegen,
        expr.operand,
        expr.target_type_ref,
        "rt_is_instance_of_type",
        ctx,
    )
    codegen.emit_bool_normalize()


def _emit_array_ctor_expr(codegen: CodeGenerator, expr: ArrayCtorExprS, ctx: EmitContext) -> None:
    runtime_kind = codegen_types.array_element_runtime_kind_for_type_ref(expr.element_type_ref)
    runtime_ctor = ARRAY_CONSTRUCTOR_RUNTIME_CALLS[runtime_kind]
    emit_expr(codegen, expr.length_expr, ctx)
    codegen.emit_push("rax")
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    _sync_named_roots_if_needed(codegen, ctx, _named_root_sync_local_ids_for_expr(ctx, expr))
    rooted_runtime_arg_count = codegen.emit_runtime_call_arg_temp_roots(ctx.layout, runtime_ctor, 1, span=expr.span)
    codegen.emit_pop("rdi")
    codegen.emit_aligned_call(runtime_ctor)
    if rooted_runtime_arg_count > 0:
        codegen.emit_clear_runtime_call_arg_temp_roots(ctx.layout, rooted_runtime_arg_count)
    _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_array_len_expr(codegen: CodeGenerator, expr: ArrayLenExpr, ctx: EmitContext) -> None:
    if not codegen.collection_fast_paths_enabled:
        _emit_named_call(
            codegen,
            ARRAY_LEN_RUNTIME_CALL,
            [expr.target],
            TYPE_NAME_U64,
            ctx,
            named_root_local_ids=_named_root_sync_local_ids_for_expr(ctx, expr),
        )
        return
    emit_expr(codegen, expr.target, ctx)
    _emit_array_null_check(codegen, ctx=ctx)
    codegen.asm.instr(f"mov rax, {array_length_operand('rax')}")


def _emit_array_null_check(codegen: CodeGenerator, *, ctx: EmitContext) -> None:
    non_null_label = codegen_symbols.next_label(ctx.fn_name, "array_non_null", ctx.label_counter)
    panic_message_label = codegen.runtime_panic_message_label(ARRAY_API_NULL_PANIC_MESSAGE)

    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"jne {non_null_label}")
    codegen.asm.instr(f"lea rdi, [rip + {panic_message_label}]")
    codegen.emit_aligned_call("rt_panic")
    codegen.asm.label(non_null_label)


def _emit_array_index_bounds_check(codegen: CodeGenerator, dispatch: RuntimeDispatch, *, ctx: EmitContext) -> None:
    in_bounds_label = codegen_symbols.next_label(ctx.fn_name, "array_index_in_bounds", ctx.label_counter)
    panic_message_label = codegen.runtime_panic_message_label(
        f"{runtime_dispatch_call_name(dispatch)}: index out of bounds"
    )

    codegen.asm.instr("cmp rcx, 0")
    codegen.asm.instr(f"jl {in_bounds_label}_panic")
    codegen.asm.instr(f"cmp rcx, {array_length_operand('rax')}")
    codegen.asm.instr(f"jb {in_bounds_label}")
    codegen.asm.label(f"{in_bounds_label}_panic")
    codegen.asm.instr(f"lea rdi, [rip + {panic_message_label}]")
    codegen.emit_aligned_call("rt_panic")
    codegen.asm.label(in_bounds_label)


def _emit_array_direct_element_load(
    codegen: CodeGenerator,
    element_type_ref: SemanticTypeRef,
    *,
    array_register: str,
    index_register: str,
    span,
) -> None:
    element_type_name = semantic_type_canonical_name(element_type_ref)
    if element_type_name == TYPE_NAME_U8:
        address = array_data_index_address(array_register, index_register, element_size=1)
        codegen.asm.instr(f"movzx eax, byte ptr {address}")
        return
    if element_type_name == TYPE_NAME_UNIT:
        codegen_types.raise_codegen_error("array direct loads do not support unit elements", span=span)

    address = array_data_index_address(array_register, index_register, element_size=8)
    codegen.asm.instr(f"mov rax, qword ptr {address}")


def _is_direct_array_index_read_dispatch(dispatch: SemanticDispatch) -> bool:
    return (
        isinstance(dispatch, RuntimeDispatch)
        and dispatch.runtime_kind is not None
        and dispatch.operation in {CollectionOpKind.INDEX_GET, CollectionOpKind.ITER_GET}
    )


def _emit_call_expr(codegen: CodeGenerator, expr: CallExprS, ctx: EmitContext) -> None:
    target = expr.target
    named_root_local_ids = _named_root_sync_local_ids_for_expr(ctx, expr)
    if isinstance(target, FunctionCallTarget):
        _emit_named_call(codegen, target.function_id.name, expr.args, expr.type_ref, ctx, named_root_local_ids=named_root_local_ids)
        return
    if isinstance(target, StaticMethodCallTarget):
        _emit_named_call(
            codegen, _method_label(target.method_id, ctx), expr.args, expr.type_ref, ctx, named_root_local_ids=named_root_local_ids
        )
        return
    if isinstance(target, InstanceMethodCallTarget):
        _emit_named_call(
            codegen,
            _method_label(target.method_id, ctx),
            [target.access.receiver, *expr.args],
            expr.type_ref,
            ctx,
            named_root_local_ids=named_root_local_ids,
        )
        return
    if isinstance(target, VirtualMethodCallTarget):
        _emit_virtual_method_call(codegen, expr, target, ctx, named_root_local_ids=named_root_local_ids)
        return
    if isinstance(target, InterfaceMethodCallTarget):
        _emit_interface_method_call(codegen, expr, target, ctx, named_root_local_ids=named_root_local_ids)
        return
    if isinstance(target, ConstructorCallTarget):
        _emit_named_call(
            codegen, _constructor_label(target.constructor_id, ctx), expr.args, expr.type_ref, ctx, named_root_local_ids=named_root_local_ids
        )
        return
    if isinstance(target, ConstructorInitCallTarget):
        _emit_named_call(
            codegen,
            _constructor_init_label(target.constructor_id, ctx),
            [target.access.receiver, *expr.args],
            expr.type_ref,
            ctx,
            named_root_local_ids=named_root_local_ids,
        )
        return
    _emit_callable_value_call(codegen, expr, target.callee, ctx, named_root_local_ids=named_root_local_ids)


def _emit_callable_value_call(
    codegen: CodeGenerator,
    expr: CallExprS,
    callee: SemanticExpr,
    ctx: EmitContext,
    *,
    named_root_local_ids: frozenset[LocalId] | None,
) -> None:
    _emit_call_sequence(
        codegen,
        call_arguments=expr.args,
        return_type_ref=expr.type_ref,
        ctx=ctx,
        callee_expr=callee,
        temp_root_spans=[expr.span] * len(expr.args),
        named_root_local_ids=named_root_local_ids,
    )


def _emit_interface_method_call(
    codegen: CodeGenerator,
    expr: CallExprS,
    target: InterfaceMethodCallTarget,
    ctx: EmitContext,
    *,
    named_root_local_ids: frozenset[LocalId] | None,
) -> None:
    descriptor_symbol = ctx.declaration_tables.interface_descriptor_symbol(target.interface_id)
    if descriptor_symbol is None:
        codegen_types.raise_codegen_error(
            f"missing interface descriptor symbol for {target.interface_id}", span=expr.span
        )

    interface_slot = _interface_slot(target.interface_id, ctx)
    method_slot = _interface_method_slot(target.method_id, ctx)
    _emit_indirect_method_call(
        codegen,
        receiver=target.access.receiver,
        extra_args=expr.args,
        return_type_ref=expr.type_ref,
        ctx=ctx,
        call_span=expr.span,
        named_root_local_ids=named_root_local_ids,
        resolve_method_pointer=lambda: _emit_interface_method_lookup(
            codegen,
            ctx,
            descriptor_symbol=descriptor_symbol,
            interface_slot=interface_slot,
            method_slot=method_slot,
        ),
    )


def _emit_virtual_method_call(
    codegen: CodeGenerator,
    expr: CallExprS,
    target: VirtualMethodCallTarget,
    ctx: EmitContext,
    *,
    named_root_local_ids: frozenset[LocalId] | None,
) -> None:
    slot_index = _class_virtual_slot_index(target, ctx, span=expr.span)
    _emit_indirect_method_call(
        codegen,
        receiver=target.access.receiver,
        extra_args=expr.args,
        return_type_ref=expr.type_ref,
        ctx=ctx,
        call_span=expr.span,
        named_root_local_ids=named_root_local_ids,
        resolve_method_pointer=lambda: _emit_virtual_method_lookup(codegen, ctx, slot_index=slot_index),
    )


def _emit_indirect_method_call(
    codegen: CodeGenerator,
    *,
    receiver: SemanticExpr,
    extra_args: list[SemanticExpr],
    return_type_ref: SemanticTypeRef | str,
    ctx: EmitContext,
    call_span,
    named_root_local_ids: frozenset[LocalId] | None,
    resolve_method_pointer: Callable[[], None],
) -> None:
    temp_root_base = ctx.temp_root_depth[0]
    receiver_temp_index = temp_root_base
    rooted_temp_arg_count = 1

    emit_expr(codegen, receiver, ctx)
    codegen.emit_temp_root_slot_store(ctx.layout, receiver_temp_index, "rax", span=call_span)
    ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count

    call_arguments = [receiver, *extra_args]
    call_argument_type_names = [_canonical_expr_type_name(arg) for arg in call_arguments]
    reference_arg_indices = {
        index
        for index, type_name in enumerate(call_argument_type_names)
        if codegen_types.is_reference_type_name(type_name)
    }

    for arg_index in range(len(extra_args) - 1, -1, -1):
        arg = extra_args[arg_index]
        emit_expr(codegen, arg, ctx)
        codegen.emit_push("rax")
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
    codegen.emit_push("rax")

    resolve_method_pointer()
    codegen.asm.instr("mov r11, rax")

    arg_locations = plan_sysv_arg_locations(call_argument_type_names)
    stack_arg_indices = [
        index
        for index, (location_kind, _location_register, _stack_index) in enumerate(arg_locations)
        if location_kind == "stack"
    ]

    _sync_named_roots_if_needed(codegen, ctx, named_root_local_ids)
    stack_base_register = "rsp"
    if stack_arg_indices:
        codegen.asm.instr("mov r10, rsp")
        stack_base_register = "r10"
    for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
        arg_operand = stack_slot_operand(stack_base_register, arg_index * 8)
        if location_kind == "int_reg":
            codegen.asm.instr(f"mov {location_register}, {arg_operand}")
        elif location_kind == "float_reg":
            codegen.asm.instr(f"movq {location_register}, {arg_operand}")
    for arg_index in reversed(stack_arg_indices):
        codegen.asm.instr(f"mov rax, {stack_slot_operand(stack_base_register, arg_index * 8)}")
        codegen.emit_push("rax")

    codegen.emit_aligned_call("r11")

    cleanup_slot_count = len(call_arguments) + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.emit_stack_release(cleanup_slot_count * 8)
    return_type_name = return_type_ref if isinstance(return_type_ref, str) else semantic_type_canonical_name(return_type_ref)
    if return_type_name == TYPE_NAME_DOUBLE:
        codegen.asm.instr("movq rax, xmm0")
    elif return_type_name == TYPE_NAME_UNIT:
        codegen.asm.instr("mov rax, 0")

    codegen.emit_clear_temp_root_slots(ctx.layout, temp_root_base, rooted_temp_arg_count)
    ctx.temp_root_depth[0] = temp_root_base


def _emit_interface_method_lookup(
    codegen: CodeGenerator,
    ctx: EmitContext,
    *,
    descriptor_symbol: str,
    interface_slot: int,
    method_slot: int,
) -> None:
    non_null_label = codegen_symbols.next_label(ctx.fn_name, "interface_call_non_null", ctx.label_counter)
    interface_match_label = codegen_symbols.next_label(ctx.fn_name, "interface_call_match", ctx.label_counter)

    codegen.asm.instr("mov rcx, qword ptr [rsp]")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr(f"jne {non_null_label}")
    codegen.emit_aligned_call("rt_panic_null_deref")
    codegen.asm.label(non_null_label)
    codegen.asm.instr(f"mov rcx, {object_type_operand('rcx')}")
    codegen.asm.instr(f"mov rax, {interface_tables_operand('rcx')}")
    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"je {interface_match_label}")
    codegen.asm.instr(f"mov rax, {interface_table_entry_operand('rax', interface_slot)}")
    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"je {interface_match_label}")
    codegen.asm.instr(f"mov rax, {interface_method_entry_operand('rax', method_slot)}")
    codegen.asm.instr("test rax, rax")
    codegen.asm.instr(f"jne {interface_match_label}_done")
    message_label = codegen.runtime_panic_message_label("interface dispatch: null interface method entry")
    codegen.asm.instr(f"lea rdi, [rip + {message_label}]")
    codegen.emit_aligned_call("rt_panic")
    codegen.asm.label(interface_match_label)
    codegen.asm.instr(f"mov rdi, {type_debug_name_operand('rcx')}")
    codegen.asm.instr(f"lea rsi, [rip + {descriptor_symbol}]")
    codegen.asm.instr(f"mov rsi, {interface_debug_name_operand('rsi')}")
    codegen.emit_aligned_call("rt_panic_bad_cast")
    codegen.asm.label(f"{interface_match_label}_done")


def _emit_virtual_method_lookup(codegen: CodeGenerator, ctx: EmitContext, *, slot_index: int) -> None:
    non_null_label = codegen_symbols.next_label(ctx.fn_name, "virtual_call_non_null", ctx.label_counter)
    codegen.asm.instr("mov rcx, qword ptr [rsp]")
    codegen.asm.instr("test rcx, rcx")
    codegen.asm.instr(f"jne {non_null_label}")
    codegen.emit_aligned_call("rt_panic_null_deref")
    codegen.asm.label(non_null_label)
    codegen.asm.instr(f"mov rcx, {object_type_operand('rcx')}")
    codegen.asm.instr(f"mov rcx, {class_vtable_operand('rcx')}")
    codegen.asm.instr(f"mov rax, {class_vtable_entry_operand('rcx', slot_index)}")


def _emit_named_call(
    codegen: CodeGenerator,
    target_name: str,
    call_arguments: list[SemanticExpr],
    return_type_ref: SemanticTypeRef | str,
    ctx: EmitContext,
    *,
    named_root_local_ids: frozenset[LocalId] | None = None,
) -> None:
    runtime_metadata = _runtime_call_metadata_for_target(target_name)
    runtime_hook_span = (
        call_arguments[0].span
        if runtime_metadata is not None and runtime_metadata.emits_safepoint_hooks and call_arguments
        else None
    )
    _emit_call_sequence(
        codegen,
        call_arguments=call_arguments,
        return_type_ref=return_type_ref,
        ctx=ctx,
        target_name=target_name,
        temp_root_spans=[arg.span for arg in call_arguments],
        runtime_hook_span=runtime_hook_span,
        named_root_local_ids=named_root_local_ids,
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
    named_root_local_ids: frozenset[LocalId] | None = None,
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
    runtime_metadata = _runtime_call_metadata_for_target(target_name)
    should_temp_root_reference_args = runtime_metadata is None or runtime_metadata.may_gc
    should_sync_named_roots = runtime_metadata is None or runtime_metadata.may_gc
    temp_root_base = ctx.temp_root_depth[0]
    if runtime_hook_span is not None:
        _emit_runtime_call_hooks_before(
            codegen,
            runtime_hook_span.start.line,
            runtime_hook_span.start.column,
            ctx,
        )
    rooted_temp_arg_count = 0
    call_scratch_base = ctx.call_scratch_depth[0]
    can_use_call_scratch_fast_path = (
        target_name is not None
        and callee_expr is None
        and not stack_arg_indices
        and call_scratch_base + len(call_arguments) <= len(layout.call_scratch_slot_offsets)
    )

    if can_use_call_scratch_fast_path:
        staged_call_arg_count = 0
        for arg_index in range(len(call_arguments) - 1, -1, -1):
            emit_expr(codegen, call_arguments[arg_index], ctx)
            scratch_slot_index = call_scratch_base + staged_call_arg_count
            codegen.asm.instr(f"mov {offset_operand(layout.call_scratch_slot_offsets[scratch_slot_index])}, rax")
            staged_call_arg_count += 1
            ctx.call_scratch_depth[0] = call_scratch_base + staged_call_arg_count
            if should_temp_root_reference_args and arg_index in reference_arg_indices:
                codegen.emit_temp_root_slot_store(
                    layout,
                    temp_root_base + rooted_temp_arg_count,
                    "rax",
                    span=temp_root_spans[arg_index],
                )
                rooted_temp_arg_count += 1
                ctx.temp_root_depth[0] = temp_root_base + rooted_temp_arg_count

        if should_sync_named_roots:
            _sync_named_roots_if_needed(codegen, ctx, named_root_local_ids)

        for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
            scratch_slot_index = call_scratch_base + (len(call_arguments) - 1 - arg_index)
            arg_operand = offset_operand(layout.call_scratch_slot_offsets[scratch_slot_index])
            if location_kind == "int_reg":
                codegen.asm.instr(f"mov {location_register}, {arg_operand}")
            elif location_kind == "float_reg":
                codegen.asm.instr(f"movq {location_register}, {arg_operand}")

        codegen.emit_aligned_call(target_name)

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
        ctx.call_scratch_depth[0] = call_scratch_base
        if runtime_hook_span is not None:
            _emit_runtime_call_hooks_after(codegen, ctx)
        return

    for arg_index in range(len(call_arguments) - 1, -1, -1):
        emit_expr(codegen, call_arguments[arg_index], ctx)
        codegen.emit_push("rax")
        if should_temp_root_reference_args and arg_index in reference_arg_indices:
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
    if should_sync_named_roots:
        _sync_named_roots_if_needed(codegen, ctx, named_root_local_ids)
    stack_base_register = "rsp"
    if stack_arg_indices:
        codegen.asm.instr("mov r10, rsp")
        stack_base_register = "r10"
    for arg_index, (location_kind, location_register, _stack_index) in enumerate(arg_locations):
        arg_operand = stack_slot_operand(stack_base_register, arg_index * 8)
        if location_kind == "int_reg":
            codegen.asm.instr(f"mov {location_register}, {arg_operand}")
        elif location_kind == "float_reg":
            codegen.asm.instr(f"movq {location_register}, {arg_operand}")
    for arg_index in reversed(stack_arg_indices):
        codegen.asm.instr(f"mov rax, {stack_slot_operand(stack_base_register, arg_index * 8)}")
        codegen.emit_push("rax")
    codegen.emit_aligned_call(call_target)
    cleanup_slot_count = len(call_arguments) + len(stack_arg_indices)
    if cleanup_slot_count > 0:
        codegen.emit_stack_release(cleanup_slot_count * 8)
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
    ctx.call_scratch_depth[0] = call_scratch_base
    if runtime_hook_span is not None:
        _emit_runtime_call_hooks_after(codegen, ctx)


def _emit_index_read_expr(codegen: CodeGenerator, expr: IndexReadExpr, ctx: EmitContext) -> None:
    if codegen.collection_fast_paths_enabled and _is_direct_array_index_read_dispatch(expr.dispatch):
        _emit_direct_array_index_read_expr(codegen, expr, ctx)
        return
    _emit_dispatch_call(
        codegen,
        expr.dispatch,
        [expr.target, expr.index],
        expr.type_ref,
        ctx,
        span=expr.span,
        named_root_local_ids=_named_root_sync_local_ids_for_expr(ctx, expr),
    )


def _emit_direct_array_index_read_expr(codegen: CodeGenerator, expr: IndexReadExpr, ctx: EmitContext) -> None:
    assert isinstance(expr.dispatch, RuntimeDispatch)

    emit_expr(codegen, expr.index, ctx)
    codegen.emit_push("rax")
    emit_expr(codegen, expr.target, ctx)
    codegen.emit_pop("rcx")
    _emit_array_null_check(codegen, ctx=ctx)
    _emit_array_index_bounds_check(codegen, expr.dispatch, ctx=ctx)
    _emit_array_direct_element_load(
        codegen,
        expr.type_ref,
        array_register="rax",
        index_register="rcx",
        span=expr.span,
    )


def _emit_slice_read_expr(codegen: CodeGenerator, expr: SliceReadExpr, ctx: EmitContext) -> None:
    _emit_dispatch_call(
        codegen,
        expr.dispatch,
        [expr.target, expr.begin, expr.end],
        expr.type_ref,
        ctx,
        span=expr.span,
        named_root_local_ids=_named_root_sync_local_ids_for_expr(ctx, expr),
    )


def _emit_string_literal_bytes_expr(codegen: CodeGenerator, expr: StringLiteralBytesExpr, ctx: EmitContext) -> None:
    label_and_len = ctx.string_literal_labels.get(expr.literal_text)
    if label_and_len is None:
        codegen_types.raise_codegen_error("missing string literal lowering metadata", span=expr.span)
    data_label, data_len = label_and_len
    _emit_runtime_call_hooks_before(codegen, expr.span.start.line, expr.span.start.column, ctx)
    _sync_named_roots_if_needed(codegen, ctx, _named_root_sync_local_ids_for_expr(ctx, expr))
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
    codegen.emit_push("rax")
    emit_expr(codegen, expr.right, ctx)
    codegen.asm.instr("mov rcx, rax")
    codegen.emit_pop("rax")
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


def _runtime_call_metadata_for_target(target_name: str | None) -> RuntimeCallMetadata | None:
    if target_name is None or not codegen_symbols.is_runtime_call_name(target_name):
        return None
    return runtime_call_metadata(target_name)


def _runtime_call_emits_safepoint_hooks(target_name: str) -> bool:
    return runtime_call_metadata(target_name).emits_safepoint_hooks


def _runtime_call_may_gc(target_name: str) -> bool:
    return runtime_call_metadata(target_name).may_gc


def _sync_named_roots_if_needed(
    codegen: CodeGenerator,
    ctx: EmitContext,
    live_local_ids: frozenset[LocalId] | None,
) -> frozenset[LocalId] | None:
    if ctx.dirty_named_root_local_ids is None:
        codegen.emit_named_root_slot_updates(ctx.layout, local_ids=live_local_ids)
        return live_local_ids

    local_ids_to_sync = _dirty_named_root_local_ids_to_sync(ctx, live_local_ids)
    codegen.emit_named_root_slot_updates(ctx.layout, local_ids=local_ids_to_sync)
    ctx.mark_named_roots_synced(local_ids_to_sync)
    return local_ids_to_sync


def _dirty_named_root_local_ids_to_sync(
    ctx: EmitContext,
    live_local_ids: frozenset[LocalId] | None,
) -> frozenset[LocalId]:
    if ctx.dirty_named_root_local_ids is None:
        return frozenset() if live_local_ids is None else live_local_ids
    if live_local_ids is None:
        return frozenset(ctx.dirty_named_root_local_ids)
    return frozenset(local_id for local_id in live_local_ids if local_id in ctx.dirty_named_root_local_ids)


def _named_root_sync_local_ids_for_expr(
    ctx: EmitContext, expr: SemanticExpr
) -> frozenset[LocalId] | None:
    if ctx.named_root_liveness is None:
        return None
    return ctx.named_root_liveness.for_expr(expr)


def _named_root_sync_local_ids_for_lvalue_call(
    ctx: EmitContext, target: SemanticLValue
) -> frozenset[LocalId] | None:
    if ctx.named_root_liveness is None:
        return None
    return ctx.named_root_liveness.for_lvalue_call(target)


def _method_label(method_id: MethodId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.method_label(method_id)
    if label is None:
        raise ValueError(f"Missing method label for {method_id}")
    return label


def _dispatch_target_name(dispatch: RuntimeDispatch | MethodDispatch, ctx: EmitContext) -> str:
    if isinstance(dispatch, RuntimeDispatch):
        return runtime_dispatch_call_name(dispatch)
    return _method_label(dispatch.method_id, ctx)


def _emit_dispatch_call(
    codegen: CodeGenerator,
    dispatch: SemanticDispatch,
    call_arguments: list[SemanticExpr],
    return_type_ref: SemanticTypeRef | str,
    ctx: EmitContext,
    *,
    span,
    named_root_local_ids: frozenset[LocalId] | None = None,
) -> None:
    if isinstance(dispatch, (RuntimeDispatch, MethodDispatch)):
        _emit_named_call(
            codegen,
            _dispatch_target_name(dispatch, ctx),
            call_arguments,
            return_type_ref,
            ctx,
            named_root_local_ids=named_root_local_ids,
        )
        return

    if not call_arguments:
        codegen_types.raise_codegen_error("virtual collection dispatch requires a receiver argument", span=span)

    slot_index = _collection_virtual_slot_index(dispatch, ctx, span=span)
    _emit_indirect_method_call(
        codegen,
        receiver=call_arguments[0],
        extra_args=call_arguments[1:],
        return_type_ref=return_type_ref,
        ctx=ctx,
        call_span=span,
        named_root_local_ids=named_root_local_ids,
        resolve_method_pointer=lambda: _emit_virtual_method_lookup(codegen, ctx, slot_index=slot_index),
    )


def _class_virtual_slot_index(target: VirtualMethodCallTarget, ctx: EmitContext, *, span) -> int:
    receiver_class_id = target.access.receiver_type_ref.class_id
    if receiver_class_id is None:
        codegen_types.raise_codegen_error("virtual call receiver must have a class type at codegen", span=span)
    return _virtual_slot_index(
        ctx,
        receiver_class_id=receiver_class_id,
        slot_owner_class_id=target.slot_owner_class_id,
        slot_method_name=target.slot_method_name,
        span=span,
    )


def _collection_virtual_slot_index(dispatch: VirtualMethodDispatch, ctx: EmitContext, *, span) -> int:
    return _virtual_slot_index(
        ctx,
        receiver_class_id=dispatch.receiver_class_id,
        slot_owner_class_id=dispatch.slot_owner_class_id,
        slot_method_name=dispatch.method_name,
        span=span,
    )


def _virtual_slot_index(
    ctx: EmitContext,
    *,
    receiver_class_id: ClassId,
    slot_owner_class_id: ClassId,
    slot_method_name: str,
    span,
) -> int:
    slot_index = ctx.declaration_tables.class_virtual_slot_index(receiver_class_id, slot_owner_class_id, slot_method_name)
    if slot_index is None:
        codegen_types.raise_codegen_error(
            (
                "missing virtual slot metadata for "
                f"'{receiver_class_id.name}.{slot_owner_class_id.name}.{slot_method_name}'"
            ),
            span=span,
        )
    return slot_index


def _interface_method_slot(method_id: InterfaceMethodId, ctx: EmitContext) -> int:
    slot = ctx.declaration_tables.interface_method_slot(method_id)
    if slot is None:
        raise ValueError(f"Missing interface method slot for {method_id}")
    return slot


def _interface_slot(interface_id: InterfaceId, ctx: EmitContext) -> int:
    slot = ctx.declaration_tables.interface_slot(interface_id)
    if slot is None:
        raise ValueError(f"Missing interface slot for {interface_id}")
    return slot


def _constructor_label(constructor_id: ConstructorId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.constructor_label(constructor_id)
    if label is None:
        raise ValueError(f"Missing constructor label for {constructor_id}")
    return label


def _constructor_init_label(constructor_id: ConstructorId, ctx: EmitContext) -> str:
    label = ctx.declaration_tables.constructor_init_label(constructor_id)
    if label is None:
        raise ValueError(f"Missing constructor init label for {constructor_id}")
    return label
