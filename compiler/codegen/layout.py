from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.types as codegen_types

from compiler.codegen.model import FunctionLayout, LayoutSlot, TEMP_RUNTIME_ROOT_SLOT_COUNT
from compiler.semantic.ir import *
from compiler.semantic.symbols import LocalId


@dataclass(frozen=True)
class _SlotSpec:
    key: str
    display_name: str
    type_name: str
    local_id: LocalId | None = None
    is_param: bool = False


def _build_function_layout(
    slot_specs: list[_SlotSpec],
    *,
    needs_temp_runtime_roots: bool,
    max_call_temp_root_slots: int,
) -> FunctionLayout:
    slot_offsets = {slot_spec.key: -(8 * index) for index, slot_spec in enumerate(slot_specs, start=1)}
    root_slot_keys = [slot_spec.key for slot_spec in slot_specs if codegen_types.is_reference_type_name(slot_spec.type_name)]
    root_slot_indices = {key: index for index, key in enumerate(root_slot_keys)}

    temp_root_slot_count = 0
    if needs_temp_runtime_roots:
        temp_root_slot_count = max(TEMP_RUNTIME_ROOT_SLOT_COUNT, max_call_temp_root_slots)

    temp_root_slot_start_index = len(root_slot_keys)
    root_slot_count = len(root_slot_keys) + temp_root_slot_count

    root_slot_offsets: dict[str, int] = {}
    root_slots_base_offset = -(8 * (len(slot_specs) + root_slot_count)) if root_slot_count > 0 else 0
    for index, key in enumerate(root_slot_keys):
        root_slot_offsets[key] = root_slots_base_offset + (8 * index)
    temp_root_slot_offsets = [
        root_slots_base_offset + (8 * (len(root_slot_keys) + index)) for index in range(temp_root_slot_count)
    ]

    bytes_for_value_slots = len(slot_specs) * 8
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
            type_name=slot_spec.type_name,
            offset=slot_offsets[slot_spec.key],
            local_id=slot_spec.local_id,
            root_index=root_slot_indices.get(slot_spec.key),
            root_offset=root_slot_offsets.get(slot_spec.key),
        )
        for slot_spec in slot_specs
    ]
    root_slots = [slot for slot in slots if slot.root_index is not None and slot.root_offset is not None]

    slot_names = [slot.key for slot in slots]
    slot_type_names = {slot.key: slot.type_name for slot in slots}
    local_slot_offsets = {slot.local_id: slot.offset for slot in slots if slot.local_id is not None}
    param_slot_offsets = {
        slot.display_name: slot.offset for slot, slot_spec in zip(slots, slot_specs) if slot_spec.is_param
    }
    root_slot_names = [slot.key for slot in root_slots]

    return FunctionLayout(
        slots=slots,
        slot_names=slot_names,
        slot_offsets=slot_offsets,
        local_slot_offsets=local_slot_offsets,
        param_slot_offsets=param_slot_offsets,
        slot_type_names=slot_type_names,
        root_slots=root_slots,
        root_slot_names=root_slot_names,
        root_slot_indices=root_slot_indices,
        root_slot_offsets=root_slot_offsets,
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


def _local_slot_specs(fn: SemanticFunction) -> list[_SlotSpec]:
    seen_display_names: set[str] = set()
    slot_specs: list[_SlotSpec] = []
    local_infos = sorted(fn.local_info_by_id.values(), key=lambda local_info: local_info.local_id.ordinal)
    for local_info in local_infos:
        slot_specs.append(
            _SlotSpec(
                key=_local_slot_key(local_info.display_name, local_info.local_id.ordinal, seen_display_names),
                display_name=local_info.display_name,
                type_name=local_info.type_name,
                local_id=local_info.local_id,
                is_param=local_info.binding_kind in {"receiver", "param"},
            )
        )
    return slot_specs


def _legacy_slot_specs(fn: SemanticFunction) -> list[_SlotSpec]:
    ordered_slot_names: list[str] = []
    local_types_by_name: dict[str, str] = {}
    seen_names: set[str] = set()
    for param in fn.params:
        if param.name not in seen_names:
            seen_names.add(param.name)
            ordered_slot_names.append(param.name)
            local_types_by_name[param.name] = param.type_name

    for stmt in fn.body.statements:
        _collect_locals(stmt, local_types_by_name)

    for name in sorted(local_types_by_name):
        if name not in seen_names:
            seen_names.add(name)
            ordered_slot_names.append(name)

    return [
        _SlotSpec(
            key=name,
            display_name=name,
            type_name=local_types_by_name[name],
            is_param=name in {param.name for param in fn.params},
        )
        for name in ordered_slot_names
    ]


def _constructor_slot_specs(cls: SemanticClass, ctor_layout, *, constructor_object_slot_name: str) -> list[_SlotSpec]:
    field_types_by_name = {field.name: field.type_name for field in cls.fields}
    ordered_slot_names = [*ctor_layout.param_field_names, constructor_object_slot_name]
    return [
        _SlotSpec(
            key=slot_name,
            display_name=slot_name,
            type_name=(cls.class_id.name if slot_name == constructor_object_slot_name else field_types_by_name[slot_name]),
            is_param=slot_name in ctor_layout.param_field_names,
        )
        for slot_name in ordered_slot_names
    ]


def _collect_locals(stmt: SemanticStmt, local_types_by_name: dict[str, str]) -> None:
    if isinstance(stmt, SemanticBlock):
        for nested in stmt.statements:
            _collect_locals(nested, local_types_by_name)
        return
    if isinstance(stmt, SemanticVarDecl):
        if stmt.name is None or stmt.type_name is None:
            raise ValueError("legacy layout fallback requires SemanticVarDecl name/type metadata when local_info_by_id is absent")
        local_types_by_name.setdefault(stmt.name, stmt.type_name)
        return
    if isinstance(stmt, SemanticIf):
        _collect_locals(stmt.then_block, local_types_by_name)
        if stmt.else_block is not None:
            _collect_locals(stmt.else_block, local_types_by_name)
        return
    if isinstance(stmt, SemanticWhile):
        _collect_locals(stmt.body, local_types_by_name)
        return
    if isinstance(stmt, SemanticForIn):
        local_types_by_name.setdefault(stmt.element_name, stmt.element_type_name)
        _collect_locals(stmt.body, local_types_by_name)


def _lvalue_needs_temp_runtime_roots(target) -> bool:
    if isinstance(target, LocalLValue):
        return False
    if isinstance(target, FieldLValue):
        return _expr_needs_temp_runtime_roots(target.receiver)
    if isinstance(target, IndexLValue):
        return True
    if isinstance(target, SliceLValue):
        return True
    return False


def _expr_needs_temp_runtime_roots(expr: SemanticExpr) -> bool:
    if isinstance(
        expr,
        (
            FunctionCallExpr,
            StaticMethodCallExpr,
            InstanceMethodCallExpr,
            InterfaceMethodCallExpr,
            ConstructorCallExpr,
            CallableValueCallExpr,
            IndexReadExpr,
            SliceReadExpr,
            ArrayCtorExprS,
            ArrayLenExpr,
            SyntheticExpr,
        ),
    ):
        return True
    if isinstance(expr, CastExprS):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, UnaryExprS):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, BinaryExprS):
        return _expr_needs_temp_runtime_roots(expr.left) or _expr_needs_temp_runtime_roots(expr.right)
    if isinstance(expr, FieldReadExpr):
        return _expr_needs_temp_runtime_roots(expr.receiver)
    return False


def _stmt_needs_temp_runtime_roots(stmt: SemanticStmt) -> bool:
    if isinstance(stmt, SemanticBlock):
        return any(_stmt_needs_temp_runtime_roots(nested) for nested in stmt.statements)
    if isinstance(stmt, SemanticVarDecl):
        return stmt.initializer is not None and _expr_needs_temp_runtime_roots(stmt.initializer)
    if isinstance(stmt, SemanticAssign):
        return _lvalue_needs_temp_runtime_roots(stmt.target) or _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, SemanticExprStmt):
        return _expr_needs_temp_runtime_roots(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return stmt.value is not None and _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, SemanticIf):
        return (
            _expr_needs_temp_runtime_roots(stmt.condition)
            or _stmt_needs_temp_runtime_roots(stmt.then_block)
            or (stmt.else_block is not None and _stmt_needs_temp_runtime_roots(stmt.else_block))
        )
    if isinstance(stmt, SemanticWhile):
        return _expr_needs_temp_runtime_roots(stmt.condition) or _stmt_needs_temp_runtime_roots(stmt.body)
    if isinstance(stmt, SemanticForIn):
        return (
            _expr_needs_temp_runtime_roots(stmt.collection)
            or codegen_types.is_reference_type_name(expression_type_name(stmt.collection))
            or _stmt_needs_temp_runtime_roots(stmt.body)
        )
    return False


def _max_call_temp_root_slots_in_expr(expr: SemanticExpr) -> int:
    def _max_rooted_sequence(call_arguments: list[SemanticExpr], *, trailing_expr: SemanticExpr | None = None) -> int:
        rooted_after = 0
        max_slots = 0

        for arg in reversed(call_arguments):
            max_slots = max(max_slots, rooted_after + _max_call_temp_root_slots_in_expr(arg))
            if codegen_types.is_reference_type_name(expression_type_name(arg)):
                rooted_after += 1
                max_slots = max(max_slots, rooted_after)

        if trailing_expr is not None:
            max_slots = max(max_slots, rooted_after + _max_call_temp_root_slots_in_expr(trailing_expr))

        return max(max_slots, rooted_after)

    if isinstance(expr, CallableValueCallExpr):
        return _max_rooted_sequence(expr.args, trailing_expr=expr.callee)
    if isinstance((expr), (FunctionCallExpr, StaticMethodCallExpr, ConstructorCallExpr)):
        return _max_rooted_sequence(expr.args)
    if isinstance(expr, InstanceMethodCallExpr):
        return _max_rooted_sequence([expr.receiver, *expr.args])
    if isinstance(expr, InterfaceMethodCallExpr):
        return max(_max_call_temp_root_slots_in_expr(expr.receiver), 1 + _max_rooted_sequence(expr.args))
    if isinstance(expr, ArrayLenExpr):
        return _max_rooted_sequence([expr.target])
    if isinstance(expr, IndexReadExpr):
        return _max_rooted_sequence([expr.target, expr.index])
    if isinstance(expr, SliceReadExpr):
        return _max_rooted_sequence([expr.target, expr.begin, expr.end])
    if isinstance(expr, ArrayCtorExprS):
        return _max_call_temp_root_slots_in_expr(expr.length_expr)
    if isinstance(expr, SyntheticExpr):
        return max((_max_call_temp_root_slots_in_expr(arg) for arg in expr.args), default=0)
    if isinstance(expr, CastExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, UnaryExprS):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, BinaryExprS):
        return max(_max_call_temp_root_slots_in_expr(expr.left), _max_call_temp_root_slots_in_expr(expr.right))
    if isinstance(expr, FieldReadExpr):
        return _max_call_temp_root_slots_in_expr(expr.receiver)
    return 0


def _max_call_temp_root_slots_in_stmt(stmt: SemanticStmt) -> int:
    if isinstance(stmt, SemanticBlock):
        return max((_max_call_temp_root_slots_in_stmt(nested) for nested in stmt.statements), default=0)
    if isinstance(stmt, SemanticVarDecl):
        return _max_call_temp_root_slots_in_expr(stmt.initializer) if stmt.initializer is not None else 0
    if isinstance(stmt, SemanticAssign):
        target_slots = 0
        if isinstance(stmt.target, FieldLValue):
            target_slots = _max_call_temp_root_slots_in_expr(stmt.target.receiver)
        elif isinstance(stmt.target, IndexLValue):
            target_slots = max(
                _max_call_temp_root_slots_in_expr(stmt.target.target),
                _max_call_temp_root_slots_in_expr(stmt.target.index),
            )
        elif isinstance(stmt.target, SliceLValue):
            target_slots = max(
                _max_call_temp_root_slots_in_expr(stmt.target.target),
                _max_call_temp_root_slots_in_expr(stmt.target.begin),
                _max_call_temp_root_slots_in_expr(stmt.target.end),
            )
        return max(target_slots, _max_call_temp_root_slots_in_expr(stmt.value))
    if isinstance(stmt, SemanticExprStmt):
        return _max_call_temp_root_slots_in_expr(stmt.expr)
    if isinstance(stmt, SemanticReturn):
        return _max_call_temp_root_slots_in_expr(stmt.value) if stmt.value is not None else 0
    if isinstance(stmt, SemanticIf):
        return max(
            _max_call_temp_root_slots_in_expr(stmt.condition),
            _max_call_temp_root_slots_in_stmt(stmt.then_block),
            _max_call_temp_root_slots_in_stmt(stmt.else_block) if stmt.else_block is not None else 0,
        )
    if isinstance(stmt, SemanticWhile):
        return max(_max_call_temp_root_slots_in_expr(stmt.condition), _max_call_temp_root_slots_in_stmt(stmt.body))
    if isinstance(stmt, SemanticForIn):
        implicit_for_in_call_slots = 1 if codegen_types.is_reference_type_name(expression_type_name(stmt.collection)) else 0
        return max(
            _max_call_temp_root_slots_in_expr(stmt.collection),
            implicit_for_in_call_slots,
            _max_call_temp_root_slots_in_stmt(stmt.body),
        )
    return 0


def build_layout(fn: SemanticFunction) -> FunctionLayout:
    if fn.body is None:
        raise ValueError("semantic layout requires a concrete function body")
    slot_specs = _local_slot_specs(fn) if fn.local_info_by_id else _legacy_slot_specs(fn)

    needs_temp_runtime_roots = any(_stmt_needs_temp_runtime_roots(stmt) for stmt in fn.body.statements)
    max_call_temp_root_slots = max((_max_call_temp_root_slots_in_stmt(stmt) for stmt in fn.body.statements), default=0)
    return _build_function_layout(
        slot_specs,
        needs_temp_runtime_roots=needs_temp_runtime_roots,
        max_call_temp_root_slots=max_call_temp_root_slots,
    )


def build_constructor_layout(cls: SemanticClass, ctor_layout, *, constructor_object_slot_name: str) -> FunctionLayout:
    slot_specs = _constructor_slot_specs(
        cls,
        ctor_layout,
        constructor_object_slot_name=constructor_object_slot_name,
    )
    initializer_exprs = [field.initializer for field in cls.fields if field.initializer is not None]
    needs_temp_runtime_roots = any(_expr_needs_temp_runtime_roots(expr) for expr in initializer_exprs)
    max_call_temp_root_slots = max((_max_call_temp_root_slots_in_expr(expr) for expr in initializer_exprs), default=0)
    return _build_function_layout(
        slot_specs,
        needs_temp_runtime_roots=needs_temp_runtime_roots,
        max_call_temp_root_slots=max_call_temp_root_slots,
    )
