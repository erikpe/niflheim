from __future__ import annotations

from dataclasses import dataclass

from compiler.codegen.abi.runtime import ARRAY_LEN_RUNTIME_CALL, runtime_call_metadata
from compiler.codegen.abi.sysv import plan_sysv_arg_locations
from compiler.codegen.effects import expr_may_execute_gc
from compiler.codegen.runtime_calls import runtime_dispatch_call_name
import compiler.codegen.types as codegen_types

from compiler.codegen.model import FunctionLayout, LayoutSlot, TEMP_RUNTIME_ROOT_SLOT_COUNT
from compiler.semantic.lowered_ir import (
    LoweredSemanticBlock,
    LoweredSemanticClass,
    LoweredSemanticForIn,
    LoweredSemanticFunction,
    LoweredSemanticIf,
    LoweredSemanticStmt,
    LoweredSemanticWhile,
)
from compiler.semantic.ir import *
from compiler.semantic.symbols import LocalId
from compiler.semantic.types import semantic_type_canonical_name, semantic_type_ref_for_class_id


@dataclass(frozen=True)
class _SlotSpec:
    key: str
    display_name: str
    type_ref: SemanticTypeRef
    local_id: LocalId | None = None
    is_param: bool = False


def _build_function_layout(
    slot_specs: list[_SlotSpec], *, needs_temp_runtime_roots: bool, max_call_temp_root_slots: int, max_call_scratch_slots: int
) -> FunctionLayout:
    slot_offsets = {slot_spec.key: -(8 * index) for index, slot_spec in enumerate(slot_specs, start=1)}
    call_scratch_slot_offsets = [
        -(8 * (len(slot_specs) + index)) for index in range(1, max_call_scratch_slots + 1)
    ]
    root_slot_keys = [
        slot_spec.key for slot_spec in slot_specs if codegen_types.is_reference_type_ref(slot_spec.type_ref)
    ]
    root_slot_indices = {key: index for index, key in enumerate(root_slot_keys)}

    temp_root_slot_count = 0
    if needs_temp_runtime_roots:
        temp_root_slot_count = max(TEMP_RUNTIME_ROOT_SLOT_COUNT, max_call_temp_root_slots)

    temp_root_slot_start_index = len(root_slot_keys)
    root_slot_count = len(root_slot_keys) + temp_root_slot_count

    root_slot_offsets: dict[str, int] = {}
    root_slots_base_offset = (
        -(8 * (len(slot_specs) + max_call_scratch_slots + root_slot_count)) if root_slot_count > 0 else 0
    )
    for index, key in enumerate(root_slot_keys):
        root_slot_offsets[key] = root_slots_base_offset + (8 * index)
    temp_root_slot_offsets = [
        root_slots_base_offset + (8 * (len(root_slot_keys) + index)) for index in range(temp_root_slot_count)
    ]

    bytes_for_value_slots = (len(slot_specs) + max_call_scratch_slots) * 8
    bytes_for_root_slots = root_slot_count * 8
    thread_state_offset = -(bytes_for_value_slots + bytes_for_root_slots + 8)
    root_frame_offset = thread_state_offset - 24 if root_slot_count > 0 else 0

    bytes_for_thread_state = 8
    bytes_for_root_frame = 24 if root_slot_count > 0 else 0
    stack_size = _align16(bytes_for_value_slots + bytes_for_root_slots + bytes_for_thread_state + bytes_for_root_frame)

    slots = [
        LayoutSlot(
            key=slot_spec.key,
            display_name=slot_spec.display_name,
            type_ref=slot_spec.type_ref,
            offset=slot_offsets[slot_spec.key],
            local_id=slot_spec.local_id,
            root_index=root_slot_indices.get(slot_spec.key),
            root_offset=root_slot_offsets.get(slot_spec.key),
        )
        for slot_spec in slot_specs
    ]
    root_slots = [slot for slot in slots if slot.root_index is not None and slot.root_offset is not None]

    slot_names = [slot.key for slot in slots]
    slot_type_refs = {slot.key: slot.type_ref for slot in slots}
    local_slot_offsets = {slot.local_id: slot.offset for slot in slots if slot.local_id is not None}
    root_slot_names = [slot.key for slot in root_slots]
    root_slot_offsets_by_local_id = {
        slot.local_id: slot.root_offset
        for slot in root_slots
        if slot.local_id is not None and slot.root_offset is not None
    }

    return FunctionLayout(
        slots=slots,
        slot_names=slot_names,
        slot_offsets=slot_offsets,
        local_slot_offsets=local_slot_offsets,
        slot_type_refs=slot_type_refs,
        call_scratch_slot_offsets=call_scratch_slot_offsets,
        root_slots=root_slots,
        root_slot_names=root_slot_names,
        root_slot_indices=root_slot_indices,
        root_slot_offsets=root_slot_offsets,
        root_slot_offsets_by_local_id=root_slot_offsets_by_local_id,
        temp_root_slot_offsets=temp_root_slot_offsets,
        temp_root_slot_start_index=temp_root_slot_start_index,
        root_slot_count=root_slot_count,
        thread_state_offset=thread_state_offset,
        root_frame_offset=root_frame_offset,
        stack_size=stack_size,
    )


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _local_slot_key(display_name: str, ordinal: int, seen_display_names: set[str]) -> str:
    if display_name not in seen_display_names:
        seen_display_names.add(display_name)
        return display_name
    return f"{display_name}@{ordinal}"


def _local_slot_specs(fn: SemanticFunction | LoweredSemanticFunction) -> list[_SlotSpec]:
    seen_display_names: set[str] = set()
    slot_specs: list[_SlotSpec] = []
    local_infos = sorted(fn.local_info_by_id.values(), key=lambda local_info: local_info.local_id.ordinal)
    for local_info in local_infos:
        slot_specs.append(
            _SlotSpec(
                key=_local_slot_key(local_info.display_name, local_info.local_id.ordinal, seen_display_names),
                display_name=local_info.display_name,
                type_ref=local_info.type_ref,
                local_id=local_info.local_id,
                is_param=local_info.binding_kind in {"receiver", "param"},
            )
        )
    return slot_specs


def _require_function_param_local_info(fn: SemanticFunction | LoweredSemanticFunction) -> None:
    param_locals = [
        local_info for local_info in fn.local_info_by_id.values() if local_info.binding_kind in {"receiver", "param"}
    ]
    if len(param_locals) != len(fn.params):
        raise ValueError("semantic layout requires owner-local metadata for every function parameter")


def _constructor_slot_specs(
    cls: SemanticClass | LoweredSemanticClass, ctor_layout, *, constructor_object_slot_name: str
) -> list[_SlotSpec]:
    field_types_by_name = {field.name: field.type_ref for field in cls.fields}
    ordered_slot_names = [*ctor_layout.param_field_names, constructor_object_slot_name]
    return [
        _SlotSpec(
            key=slot_name,
            display_name=slot_name,
            type_ref=(
                semantic_type_ref_for_class_id(cls.class_id, display_name=cls.class_id.name)
                if slot_name == constructor_object_slot_name
                else field_types_by_name[slot_name]
            ),
            is_param=slot_name in ctor_layout.param_field_names,
        )
        for slot_name in ordered_slot_names
    ]


def _function_uses_local_storage(fn: SemanticFunction | LoweredSemanticFunction) -> bool:
    if fn.params:
        return True
    return _block_uses_local_storage(fn.body)


def _block_uses_local_storage(block: SemanticBlock | LoweredSemanticBlock) -> bool:
    return any(_stmt_uses_local_storage(stmt) for stmt in block.statements)


def _stmt_uses_local_storage(stmt: SemanticStmt | LoweredSemanticStmt) -> bool:
    if isinstance(stmt, (SemanticBlock, LoweredSemanticBlock)):
        return _block_uses_local_storage(stmt)
    if isinstance(stmt, SemanticVarDecl):
        return True
    if isinstance(stmt, SemanticAssign):
        return _lvalue_uses_local_storage(stmt.target) or _expr_uses_local_storage(stmt.value)
    if isinstance(stmt, SemanticExprStmt):
        return _expr_uses_local_storage(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return stmt.value is not None and _expr_uses_local_storage(stmt.value)
    if isinstance(stmt, LoweredSemanticIf):
        return (
            _expr_uses_local_storage(stmt.condition)
            or _block_uses_local_storage(stmt.then_block)
            or (stmt.else_block is not None and _block_uses_local_storage(stmt.else_block))
        )
    if isinstance(stmt, LoweredSemanticWhile):
        return _expr_uses_local_storage(stmt.condition) or _block_uses_local_storage(stmt.body)
    if isinstance(stmt, LoweredSemanticForIn):
        return True
    return False


def _lvalue_uses_local_storage(target: SemanticLValue) -> bool:
    if isinstance(target, LocalLValue):
        return True
    if isinstance(target, FieldLValue):
        return _expr_uses_local_storage(target.receiver)
    if isinstance(target, IndexLValue):
        return _expr_uses_local_storage(target.target) or _expr_uses_local_storage(target.index)
    if isinstance(target, SliceLValue):
        return (
            _expr_uses_local_storage(target.target)
            or _expr_uses_local_storage(target.begin)
            or _expr_uses_local_storage(target.end)
        )
    return False


def _expr_uses_local_storage(expr: SemanticExpr) -> bool:
    if isinstance(expr, LocalRefExpr):
        return True
    if isinstance(expr, CastExprS):
        return _expr_uses_local_storage(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return _expr_uses_local_storage(expr.operand)
    if isinstance(expr, UnaryExprS):
        return _expr_uses_local_storage(expr.operand)
    if isinstance(expr, BinaryExprS):
        return _expr_uses_local_storage(expr.left) or _expr_uses_local_storage(expr.right)
    if isinstance(expr, FieldReadExpr):
        return _expr_uses_local_storage(expr.access.receiver)
    if isinstance(expr, CallExprS):
        access = call_target_receiver_access(expr.target)
        if access is not None and _expr_uses_local_storage(access.receiver):
            return True
        if isinstance(expr.target, CallableValueCallTarget) and _expr_uses_local_storage(expr.target.callee):
            return True
        return any(_expr_uses_local_storage(arg) for arg in expr.args)
    if isinstance(expr, ArrayLenExpr):
        return _expr_uses_local_storage(expr.target)
    if isinstance(expr, IndexReadExpr):
        return _expr_uses_local_storage(expr.target) or _expr_uses_local_storage(expr.index)
    if isinstance(expr, SliceReadExpr):
        return (
            _expr_uses_local_storage(expr.target)
            or _expr_uses_local_storage(expr.begin)
            or _expr_uses_local_storage(expr.end)
        )
    if isinstance(expr, ArrayCtorExprS):
        return _expr_uses_local_storage(expr.length_expr)
    if isinstance(expr, StringLiteralBytesExpr):
        return False
    return False


def _lvalue_needs_temp_runtime_roots(target) -> bool:
    return _max_call_temp_root_slots_for_lvalue(target) > 0


def _expr_needs_temp_runtime_roots(expr: SemanticExpr) -> bool:
    return _max_call_temp_root_slots_in_expr(expr) > 0


def _stmt_needs_temp_runtime_roots(
    stmt: SemanticStmt | LoweredSemanticStmt,
    *,
    owner: SemanticFunction | LoweredSemanticFunction | None = None,
) -> bool:
    return _max_call_temp_root_slots_in_stmt(stmt, owner=owner) > 0


def _reference_arg_indices(call_arguments: list[SemanticExpr]) -> frozenset[int]:
    return frozenset(
        index
        for index, arg in enumerate(call_arguments)
        if codegen_types.is_reference_type_name(semantic_type_canonical_name(expression_type_ref(arg)))
    )


def _runtime_reference_arg_indices(target_name: str, call_arguments: list[SemanticExpr]) -> frozenset[int]:
    metadata = runtime_call_metadata(target_name)
    if not metadata.may_gc:
        return frozenset()
    return _reference_arg_indices(call_arguments)


def _dispatch_reference_arg_indices(dispatch: SemanticDispatch, call_arguments: list[SemanticExpr]) -> frozenset[int]:
    if isinstance(dispatch, RuntimeDispatch):
        return _runtime_reference_arg_indices(runtime_dispatch_call_name(dispatch), call_arguments)
    return _reference_arg_indices(call_arguments)


def _max_rooted_sequence(
    call_arguments: list[SemanticExpr],
    *,
    rooted_arg_indices: frozenset[int],
    trailing_expr: SemanticExpr | None = None,
) -> int:
    rooted_after = 0
    max_slots = 0

    for arg_index in range(len(call_arguments) - 1, -1, -1):
        arg = call_arguments[arg_index]
        max_slots = max(max_slots, rooted_after + _max_call_temp_root_slots_in_expr(arg))
        if arg_index in rooted_arg_indices:
            rooted_after += 1
            max_slots = max(max_slots, rooted_after)

    if trailing_expr is not None:
        max_slots = max(max_slots, rooted_after + _max_call_temp_root_slots_in_expr(trailing_expr))

    return max(max_slots, rooted_after)


def _max_call_temp_root_slots_for_lvalue(target: SemanticLValue) -> int:
    if isinstance(target, LocalLValue):
        return 0
    if isinstance(target, FieldLValue):
        return _max_call_temp_root_slots_in_expr(target.receiver)
    if isinstance(target, IndexLValue):
        call_arguments = [target.target, target.index]
        return _max_rooted_sequence(
            call_arguments,
            rooted_arg_indices=_dispatch_reference_arg_indices(target.dispatch, call_arguments),
        )
    if isinstance(target, SliceLValue):
        call_arguments = [target.target, target.begin, target.end]
        return _max_rooted_sequence(
            call_arguments,
            rooted_arg_indices=_dispatch_reference_arg_indices(target.dispatch, call_arguments),
        )
    return 0


def _max_call_temp_root_slots_in_expr(expr: SemanticExpr) -> int:
    if isinstance(expr, CallExprS):
        if isinstance(expr.target, CallableValueCallTarget):
            return _max_rooted_sequence(
                expr.args,
                rooted_arg_indices=_reference_arg_indices(expr.args),
                trailing_expr=expr.target.callee,
            )
        if isinstance(expr.target, FunctionCallTarget):
            return _max_rooted_sequence(
                expr.args,
                rooted_arg_indices=(
                    _runtime_reference_arg_indices(expr.target.function_id.name, expr.args)
                    if expr.target.function_id.name.startswith("rt_")
                    else _reference_arg_indices(expr.args)
                ),
            )
        access = call_target_receiver_access(expr.target)
        if access is None:
            return _max_rooted_sequence(expr.args, rooted_arg_indices=_reference_arg_indices(expr.args))
        if isinstance(expr.target, InterfaceMethodCallTarget):
            return max(
                _max_call_temp_root_slots_in_expr(access.receiver),
                1 + _max_rooted_sequence(expr.args, rooted_arg_indices=_reference_arg_indices(expr.args)),
            )
        call_arguments = [access.receiver, *expr.args]
        return _max_rooted_sequence(call_arguments, rooted_arg_indices=_reference_arg_indices(call_arguments))
    if isinstance(expr, ArrayLenExpr):
        return _max_rooted_sequence(
            [expr.target],
            rooted_arg_indices=_runtime_reference_arg_indices(ARRAY_LEN_RUNTIME_CALL, [expr.target]),
        )
    if isinstance(expr, IndexReadExpr):
        call_arguments = [expr.target, expr.index]
        return _max_rooted_sequence(
            call_arguments,
            rooted_arg_indices=_dispatch_reference_arg_indices(expr.dispatch, call_arguments),
        )
    if isinstance(expr, SliceReadExpr):
        call_arguments = [expr.target, expr.begin, expr.end]
        return _max_rooted_sequence(
            call_arguments,
            rooted_arg_indices=_dispatch_reference_arg_indices(expr.dispatch, call_arguments),
        )
    if isinstance(expr, ArrayCtorExprS):
        return _max_rooted_sequence(
            [expr.length_expr],
            rooted_arg_indices=frozenset(),
        )
    if isinstance(expr, StringLiteralBytesExpr):
        return 0
    if isinstance(expr, CastExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, UnaryExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, BinaryExprS):
        return max(_max_call_temp_root_slots_in_expr(expr.left), _max_call_temp_root_slots_in_expr(expr.right))
    if isinstance(expr, FieldReadExpr):
        return _max_call_temp_root_slots_in_expr(expr.access.receiver)
    return 0


def _max_call_temp_root_slots_in_stmt(
    stmt: SemanticStmt | LoweredSemanticStmt,
    *,
    owner: SemanticFunction | LoweredSemanticFunction | None = None,
) -> int:
    if isinstance(stmt, (SemanticBlock, LoweredSemanticBlock)):
        return max((_max_call_temp_root_slots_in_stmt(nested, owner=owner) for nested in stmt.statements), default=0)
    if isinstance(stmt, SemanticVarDecl):
        return _max_call_temp_root_slots_in_expr(stmt.initializer) if stmt.initializer is not None else 0
    if isinstance(stmt, SemanticAssign):
        target_slots = _max_call_temp_root_slots_for_lvalue(stmt.target)
        return max(target_slots, _max_call_temp_root_slots_in_expr(stmt.value), _max_call_temp_root_slots_for_ref_array_fast_write(stmt))
    if isinstance(stmt, SemanticExprStmt):
        return _max_call_temp_root_slots_in_expr(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return _max_call_temp_root_slots_in_expr(stmt.value) if stmt.value is not None else 0
    if isinstance(stmt, LoweredSemanticIf):
        return max(
            _max_call_temp_root_slots_in_expr(stmt.condition),
            _max_call_temp_root_slots_in_stmt(stmt.then_block, owner=owner),
            _max_call_temp_root_slots_in_stmt(stmt.else_block, owner=owner) if stmt.else_block is not None else 0,
        )
    if isinstance(stmt, LoweredSemanticWhile):
        return max(
            _max_call_temp_root_slots_in_expr(stmt.condition),
            _max_call_temp_root_slots_in_stmt(stmt.body, owner=owner),
        )
    if isinstance(stmt, LoweredSemanticForIn):
        if owner is None:
            raise ValueError("for-in temp-root sizing requires owner-local metadata")
        collection_ref = local_ref_expr_for_owner(owner, stmt.collection_local_id, span=stmt.span)
        index_ref = local_ref_expr_for_owner(owner, stmt.index_local_id, span=stmt.span)
        iter_len_rooted_slots = len(_dispatch_reference_arg_indices(stmt.iter_len_dispatch, [collection_ref]))
        iter_get_rooted_slots = len(
            _dispatch_reference_arg_indices(stmt.iter_get_dispatch, [collection_ref, index_ref])
        )
        return max(
            _max_call_temp_root_slots_in_expr(stmt.collection),
            iter_len_rooted_slots,
            iter_get_rooted_slots,
            _max_call_temp_root_slots_in_stmt(stmt.body, owner=owner),
        )
    return 0


def _max_call_temp_root_slots_for_ref_array_fast_write(stmt: SemanticAssign) -> int:
    target = stmt.target
    if not isinstance(target, IndexLValue):
        return 0
    if not _is_direct_ref_array_index_write_target(target):
        return 0

    later_exprs = (target.index, target.target)
    if not any(expr_may_execute_gc(expr) for expr in later_exprs):
        return 0

    return 1 + max((_max_call_temp_root_slots_in_expr(expr) for expr in later_exprs), default=0)


def _max_staged_call_scratch_sequence(call_arguments: list[SemanticExpr]) -> int:
    staged_after = 0
    max_slots = 0

    for arg_index in range(len(call_arguments) - 1, -1, -1):
        arg = call_arguments[arg_index]
        max_slots = max(max_slots, staged_after + _max_call_scratch_slots_in_expr(arg))
        staged_after += 1
        max_slots = max(max_slots, staged_after)

    return max_slots


def _register_only_direct_call_arguments(expr: CallExprS) -> list[SemanticExpr] | None:
    if isinstance(expr.target, (CallableValueCallTarget, InterfaceMethodCallTarget)):
        return None
    access = call_target_receiver_access(expr.target)
    if access is not None:
        return [access.receiver, *expr.args]
    return list(expr.args)


def _call_uses_only_register_arguments(call_arguments: list[SemanticExpr]) -> bool:
    arg_type_names = [semantic_type_canonical_name(expression_type_ref(arg)) for arg in call_arguments]
    return all(location_kind != "stack" for location_kind, _register, _stack_index in plan_sysv_arg_locations(arg_type_names))


def _max_call_scratch_slots_for_named_call_arguments(call_arguments: list[SemanticExpr]) -> int:
    if _call_uses_only_register_arguments(call_arguments):
        return _max_staged_call_scratch_sequence(call_arguments)
    return max((_max_call_scratch_slots_in_expr(arg) for arg in call_arguments), default=0)


def _max_call_scratch_slots_in_expr(expr: SemanticExpr) -> int:
    if isinstance(expr, CallExprS):
        call_arguments = _register_only_direct_call_arguments(expr)
        if call_arguments is not None and _call_uses_only_register_arguments(call_arguments):
            return _max_staged_call_scratch_sequence(call_arguments)

        nested_exprs = list(expr.args)
        if isinstance(expr.target, CallableValueCallTarget):
            nested_exprs.append(expr.target.callee)
        else:
            access = call_target_receiver_access(expr.target)
            if access is not None:
                nested_exprs.append(access.receiver)
        return max((_max_call_scratch_slots_in_expr(nested) for nested in nested_exprs), default=0)
    if isinstance(expr, ArrayLenExpr):
        return _max_call_scratch_slots_for_named_call_arguments([expr.target])
    if isinstance(expr, IndexReadExpr):
        return _max_call_scratch_slots_for_named_call_arguments([expr.target, expr.index])
    if isinstance(expr, SliceReadExpr):
        return _max_call_scratch_slots_for_named_call_arguments([expr.target, expr.begin, expr.end])
    if isinstance(expr, ArrayCtorExprS):
        return _max_call_scratch_slots_in_expr(expr.length_expr)
    if isinstance(expr, CastExprS):
        return _max_call_scratch_slots_in_expr(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return _max_call_scratch_slots_in_expr(expr.operand)
    if isinstance(expr, UnaryExprS):
        return _max_call_scratch_slots_in_expr(expr.operand)
    if isinstance(expr, BinaryExprS):
        return max(_max_call_scratch_slots_in_expr(expr.left), _max_call_scratch_slots_in_expr(expr.right))
    if isinstance(expr, FieldReadExpr):
        return _max_call_scratch_slots_in_expr(expr.access.receiver)
    return 0


def _max_call_scratch_slots_for_lvalue(target: SemanticLValue) -> int:
    if isinstance(target, LocalLValue):
        return 0
    if isinstance(target, FieldLValue):
        return _max_call_scratch_slots_in_expr(target.receiver)
    if isinstance(target, IndexLValue):
        return max(_max_call_scratch_slots_in_expr(target.target), _max_call_scratch_slots_in_expr(target.index))
    if isinstance(target, SliceLValue):
        return max(
            _max_call_scratch_slots_in_expr(target.target),
            _max_call_scratch_slots_in_expr(target.begin),
            _max_call_scratch_slots_in_expr(target.end),
        )
    return 0


def _max_call_scratch_slots_in_stmt(stmt: SemanticStmt | LoweredSemanticStmt) -> int:
    if isinstance(stmt, (SemanticBlock, LoweredSemanticBlock)):
        return max((_max_call_scratch_slots_in_stmt(nested) for nested in stmt.statements), default=0)
    if isinstance(stmt, SemanticVarDecl):
        return _max_call_scratch_slots_in_expr(stmt.initializer) if stmt.initializer is not None else 0
    if isinstance(stmt, SemanticAssign):
        if isinstance(stmt.target, IndexLValue):
            return _max_call_scratch_slots_for_named_call_arguments([stmt.target.target, stmt.target.index, stmt.value])
        if isinstance(stmt.target, SliceLValue):
            return _max_call_scratch_slots_for_named_call_arguments(
                [stmt.target.target, stmt.target.begin, stmt.target.end, stmt.value]
            )
        return max(_max_call_scratch_slots_in_expr(stmt.value), _max_call_scratch_slots_for_lvalue(stmt.target))
    if isinstance(stmt, SemanticExprStmt):
        return _max_call_scratch_slots_in_expr(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return _max_call_scratch_slots_in_expr(stmt.value) if stmt.value is not None else 0
    if isinstance(stmt, LoweredSemanticIf):
        return max(
            _max_call_scratch_slots_in_expr(stmt.condition),
            _max_call_scratch_slots_in_stmt(stmt.then_block),
            _max_call_scratch_slots_in_stmt(stmt.else_block) if stmt.else_block is not None else 0,
        )
    if isinstance(stmt, LoweredSemanticWhile):
        return max(
            _max_call_scratch_slots_in_expr(stmt.condition),
            _max_call_scratch_slots_in_stmt(stmt.body),
        )
    if isinstance(stmt, LoweredSemanticForIn):
        return max(
            _max_call_scratch_slots_in_expr(stmt.collection),
            _max_call_scratch_slots_in_stmt(stmt.body),
        )
    return 0


def _is_direct_ref_array_index_write_target(target: IndexLValue) -> bool:
    return (
        isinstance(target.dispatch, RuntimeDispatch)
        and target.dispatch.operation is CollectionOpKind.INDEX_SET
        and target.dispatch.runtime_kind is ArrayRuntimeKind.REF
    )


def build_layout(fn: SemanticFunction | LoweredSemanticFunction) -> FunctionLayout:
    if fn.body is None:
        raise ValueError("semantic layout requires a concrete function body")
    if _function_uses_local_storage(fn) and not fn.local_info_by_id:
        raise ValueError("semantic layout requires owner-local metadata for lowered local storage")
    _require_function_param_local_info(fn)
    slot_specs = _local_slot_specs(fn)

    max_call_temp_root_slots = max(
        (_max_call_temp_root_slots_in_stmt(stmt, owner=fn) for stmt in fn.body.statements),
        default=0,
    )
    max_call_scratch_slots = max((_max_call_scratch_slots_in_stmt(stmt) for stmt in fn.body.statements), default=0)
    needs_temp_runtime_roots = max_call_temp_root_slots > 0
    return _build_function_layout(
        slot_specs,
        needs_temp_runtime_roots=needs_temp_runtime_roots,
        max_call_temp_root_slots=max_call_temp_root_slots,
        max_call_scratch_slots=max_call_scratch_slots,
    )


def build_constructor_layout(
    cls: SemanticClass | LoweredSemanticClass, ctor_layout, *, constructor_object_slot_name: str
) -> FunctionLayout:
    slot_specs = _constructor_slot_specs(cls, ctor_layout, constructor_object_slot_name=constructor_object_slot_name)
    initializer_exprs = [field.initializer for field in cls.fields if field.initializer is not None]
    max_call_temp_root_slots = max((_max_call_temp_root_slots_in_expr(expr) for expr in initializer_exprs), default=0)
    max_call_scratch_slots = max((_max_call_scratch_slots_in_expr(expr) for expr in initializer_exprs), default=0)
    needs_temp_runtime_roots = max_call_temp_root_slots > 0
    return _build_function_layout(
        slot_specs,
        needs_temp_runtime_roots=needs_temp_runtime_roots,
        max_call_temp_root_slots=max_call_temp_root_slots,
        max_call_scratch_slots=max_call_scratch_slots,
    )
