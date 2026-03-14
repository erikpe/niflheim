from __future__ import annotations

import compiler.codegen.types as codegen_types

from compiler.ast_nodes import (
    ArrayCtorExpr,
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    CallExpr,
    CastExpr,
    ExprStmt,
    Expression,
    FieldAccessExpr,
    ForInStmt,
    FunctionDecl,
    IdentifierExpr,
    IfStmt,
    IndexExpr,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from compiler.codegen.model import FunctionLayout, TEMP_RUNTIME_ROOT_SLOT_COUNT


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _collect_locals(stmt: Statement, local_types_by_name: dict[str, str]) -> None:
    if isinstance(stmt, VarDeclStmt):
        local_types_by_name.setdefault(stmt.name, codegen_types.type_ref_name(stmt.type_ref))
        return
    if isinstance(stmt, BlockStmt):
        for nested in stmt.statements:
            _collect_locals(nested, local_types_by_name)
        return
    if isinstance(stmt, IfStmt):
        _collect_locals(stmt.then_branch, local_types_by_name)
        if stmt.else_branch is not None:
            _collect_locals(stmt.else_branch, local_types_by_name)
        return
    if isinstance(stmt, WhileStmt):
        _collect_locals(stmt.body, local_types_by_name)
        return
    if isinstance(stmt, ForInStmt):
        inferred_collection_type = stmt.collection_type_name
        if not inferred_collection_type:
            if isinstance(stmt.collection_expr, IdentifierExpr):
                inferred_collection_type = local_types_by_name.get(stmt.collection_expr.name, "Obj")
            elif isinstance(stmt.collection_expr, CastExpr):
                inferred_collection_type = codegen_types.type_ref_name(stmt.collection_expr.type_ref)
            elif isinstance(stmt.collection_expr, ArrayCtorExpr):
                inferred_collection_type = codegen_types.type_ref_name(stmt.collection_expr.element_type_ref)
            else:
                inferred_collection_type = "Obj"

        inferred_element_type = stmt.element_type_name
        if not inferred_element_type and codegen_types.is_array_type_name(inferred_collection_type):
            inferred_element_type = codegen_types.array_element_type_name(inferred_collection_type, span=stmt.span)

        local_types_by_name.setdefault(stmt.coll_temp_name, inferred_collection_type)
        local_types_by_name.setdefault(stmt.len_temp_name, "i64")
        local_types_by_name.setdefault(stmt.index_temp_name, "i64")
        local_types_by_name.setdefault(stmt.element_name, inferred_element_type or "i64")
        _collect_locals(stmt.body, local_types_by_name)
        return


def _expr_needs_temp_runtime_roots(expr: Expression) -> bool:
    if isinstance(expr, CallExpr):
        return True

    if isinstance(expr, CastExpr):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, UnaryExpr):
        return _expr_needs_temp_runtime_roots(expr.operand)
    if isinstance(expr, BinaryExpr):
        return _expr_needs_temp_runtime_roots(expr.left) or _expr_needs_temp_runtime_roots(expr.right)
    if isinstance(expr, FieldAccessExpr):
        return _expr_needs_temp_runtime_roots(expr.object_expr)
    if isinstance(expr, IndexExpr):
        return True
    if isinstance(expr, ArrayCtorExpr):
        return _expr_needs_temp_runtime_roots(expr.length_expr)
    return False


def _stmt_needs_temp_runtime_roots(stmt: Statement) -> bool:
    if isinstance(stmt, VarDeclStmt):
        return stmt.initializer is not None and _expr_needs_temp_runtime_roots(stmt.initializer)
    if isinstance(stmt, AssignStmt):
        if isinstance(stmt.target, IndexExpr):
            return True
        return _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, ExprStmt):
        return _expr_needs_temp_runtime_roots(stmt.expression)
    if isinstance(stmt, ReturnStmt):
        return stmt.value is not None and _expr_needs_temp_runtime_roots(stmt.value)
    if isinstance(stmt, BlockStmt):
        return any(_stmt_needs_temp_runtime_roots(nested) for nested in stmt.statements)
    if isinstance(stmt, IfStmt):
        condition_has = _expr_needs_temp_runtime_roots(stmt.condition)
        then_has = _stmt_needs_temp_runtime_roots(stmt.then_branch)
        else_has = _stmt_needs_temp_runtime_roots(stmt.else_branch) if stmt.else_branch is not None else False
        return condition_has or then_has or else_has
    if isinstance(stmt, WhileStmt):
        return _expr_needs_temp_runtime_roots(stmt.condition) or _stmt_needs_temp_runtime_roots(stmt.body)
    if isinstance(stmt, ForInStmt):
        return _expr_needs_temp_runtime_roots(stmt.collection_expr) or _stmt_needs_temp_runtime_roots(stmt.body)
    return False


def _function_needs_temp_runtime_roots(fn: FunctionDecl) -> bool:
    return any(_stmt_needs_temp_runtime_roots(stmt) for stmt in fn.body.statements)


def _max_call_temp_root_slots_in_expr(expr: Expression) -> int:
    if isinstance(expr, CallExpr):
        receiver_slots = 1 if isinstance(expr.callee, FieldAccessExpr) else 0
        max_slots = len(expr.arguments) + receiver_slots
        max_slots = max(max_slots, _max_call_temp_root_slots_in_expr(expr.callee))
        for arg in expr.arguments:
            max_slots = max(max_slots, _max_call_temp_root_slots_in_expr(arg))
        return max_slots

    if isinstance(expr, CastExpr):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, UnaryExpr):
        return _max_call_temp_root_slots_in_expr(expr.operand)
    if isinstance(expr, BinaryExpr):
        return max(_max_call_temp_root_slots_in_expr(expr.left), _max_call_temp_root_slots_in_expr(expr.right))
    if isinstance(expr, FieldAccessExpr):
        return _max_call_temp_root_slots_in_expr(expr.object_expr)
    if isinstance(expr, IndexExpr):
        return max(
            _max_call_temp_root_slots_in_expr(expr.object_expr),
            _max_call_temp_root_slots_in_expr(expr.index_expr),
        )
    if isinstance(expr, ArrayCtorExpr):
        return _max_call_temp_root_slots_in_expr(expr.length_expr)
    return 0


def _max_call_temp_root_slots_in_stmt(stmt: Statement) -> int:
    if isinstance(stmt, VarDeclStmt):
        return _max_call_temp_root_slots_in_expr(stmt.initializer) if stmt.initializer is not None else 0
    if isinstance(stmt, AssignStmt):
        target_slots = 0
        if isinstance(stmt.target, IndexExpr):
            target_slots = max(
                _max_call_temp_root_slots_in_expr(stmt.target.object_expr),
                _max_call_temp_root_slots_in_expr(stmt.target.index_expr),
            )
        elif isinstance(stmt.target, FieldAccessExpr):
            target_slots = _max_call_temp_root_slots_in_expr(stmt.target.object_expr)
        return max(target_slots, _max_call_temp_root_slots_in_expr(stmt.value))
    if isinstance(stmt, ExprStmt):
        return _max_call_temp_root_slots_in_expr(stmt.expression)
    if isinstance(stmt, ReturnStmt):
        return _max_call_temp_root_slots_in_expr(stmt.value) if stmt.value is not None else 0
    if isinstance(stmt, BlockStmt):
        max_slots = 0
        for nested in stmt.statements:
            max_slots = max(max_slots, _max_call_temp_root_slots_in_stmt(nested))
        return max_slots
    if isinstance(stmt, IfStmt):
        max_slots = _max_call_temp_root_slots_in_expr(stmt.condition)
        max_slots = max(max_slots, _max_call_temp_root_slots_in_stmt(stmt.then_branch))
        if stmt.else_branch is not None:
            max_slots = max(max_slots, _max_call_temp_root_slots_in_stmt(stmt.else_branch))
        return max_slots
    if isinstance(stmt, WhileStmt):
        return max(
            _max_call_temp_root_slots_in_expr(stmt.condition),
            _max_call_temp_root_slots_in_stmt(stmt.body),
        )
    if isinstance(stmt, ForInStmt):
        return max(
            _max_call_temp_root_slots_in_expr(stmt.collection_expr),
            _max_call_temp_root_slots_in_stmt(stmt.body),
        )
    return 0


def _function_max_call_temp_root_slots(fn: FunctionDecl) -> int:
    max_slots = 0
    for stmt in fn.body.statements:
        max_slots = max(max_slots, _max_call_temp_root_slots_in_stmt(stmt))
    return max_slots


def build_layout(fn: FunctionDecl) -> FunctionLayout:
    ordered_slot_names: list[str] = []
    seen_names: set[str] = set()
    local_types_by_name: dict[str, str] = {}

    for param in fn.params:
        if param.name not in seen_names:
            seen_names.add(param.name)
            ordered_slot_names.append(param.name)
            local_types_by_name[param.name] = codegen_types.type_ref_name(param.type_ref)

    for stmt in fn.body.statements:
        _collect_locals(stmt, local_types_by_name)

    for name in sorted(local_types_by_name):
        if name not in seen_names:
            seen_names.add(name)
            ordered_slot_names.append(name)

    slot_offsets: dict[str, int] = {}
    for index, name in enumerate(ordered_slot_names, start=1):
        slot_offsets[name] = -(8 * index)

    root_slot_names = [name for name in ordered_slot_names if codegen_types.is_reference_type_name(local_types_by_name[name])]
    root_slot_indices = {name: index for index, name in enumerate(root_slot_names)}

    needs_temp_runtime_roots = _function_needs_temp_runtime_roots(fn)
    max_call_temp_root_slots = _function_max_call_temp_root_slots(fn)
    temp_root_slot_count = 0
    if needs_temp_runtime_roots:
        temp_root_slot_count = max(TEMP_RUNTIME_ROOT_SLOT_COUNT, max_call_temp_root_slots)
    temp_root_slot_start_index = len(root_slot_names)
    root_slot_count = len(root_slot_names) + temp_root_slot_count

    root_slot_offsets: dict[str, int] = {}
    root_slots_base_offset = -(8 * (len(ordered_slot_names) + root_slot_count)) if root_slot_count > 0 else 0
    for index, name in enumerate(root_slot_names):
        root_slot_offsets[name] = root_slots_base_offset + (8 * index)
    temp_root_slot_offsets = [
        root_slots_base_offset + (8 * (len(root_slot_names) + index))
        for index in range(temp_root_slot_count)
    ]

    bytes_for_value_slots = len(ordered_slot_names) * 8
    bytes_for_root_slots = root_slot_count * 8
    bytes_for_shadow_stack_state = 32 if root_slot_count > 0 else 0

    bytes_for_slots = bytes_for_value_slots + bytes_for_root_slots
    thread_state_offset = -(bytes_for_slots + 8) if root_slot_count > 0 else 0
    root_frame_offset = -(bytes_for_slots + 8 + 24) if root_slot_count > 0 else 0
    stack_size = _align16(bytes_for_slots + bytes_for_shadow_stack_state)
    return FunctionLayout(
        slot_names=ordered_slot_names,
        slot_offsets=slot_offsets,
        slot_type_names=local_types_by_name,
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