from __future__ import annotations

import compiler.codegen.types as codegen_types

from compiler.codegen.model import FunctionLayout, TEMP_RUNTIME_ROOT_SLOT_COUNT
from compiler.semantic_ir import (
    ArrayCtorExprS,
    ArrayLenExpr,
    BinaryExprS,
    CallableValueCallExpr,
    CastExprS,
    ConstructorCallExpr,
    FieldReadExpr,
    FieldLValue,
    FunctionCallExpr,
    IndexReadExpr,
    IndexLValue,
    InstanceMethodCallExpr,
    LocalLValue,
    SemanticBlock,
    SemanticAssign,
    SemanticExpr,
    SemanticExprStmt,
    SemanticForIn,
    SemanticFunction,
    SemanticIf,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    SliceLValue,
    SliceReadExpr,
    StaticMethodCallExpr,
    SyntheticExpr,
    UnaryExprS,
)


def for_in_temp_name(kind: str, stmt: SemanticForIn) -> str:
    start = stmt.span.start
    return f"__nif_forin_{kind}_{start.line}_{start.column}"


def _align16(size: int) -> int:
    return (size + 15) & ~15


def _collect_locals(stmt: SemanticStmt, local_types_by_name: dict[str, str]) -> None:
    if isinstance(stmt, SemanticBlock):
        for nested in stmt.statements:
            _collect_locals(nested, local_types_by_name)
        return
    if isinstance(stmt, SemanticVarDecl):
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
        local_types_by_name.setdefault(for_in_temp_name("coll", stmt), infer_expression_type_name(stmt.collection))
        local_types_by_name.setdefault(for_in_temp_name("len", stmt), "u64")
        local_types_by_name.setdefault(for_in_temp_name("index", stmt), "i64")
        local_types_by_name.setdefault(stmt.element_name, stmt.element_type_name)
        _collect_locals(stmt.body, local_types_by_name)


def infer_expression_type_name(expr: SemanticExpr) -> str:
    return getattr(expr, "type_name", getattr(expr, "result_type_name", getattr(expr, "field_type_name", "null")))


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
        return _expr_needs_temp_runtime_roots(stmt.collection) or _stmt_needs_temp_runtime_roots(stmt.body)
    return False


def _max_call_temp_root_slots_in_expr(expr: SemanticExpr) -> int:
    def _max_rooted_sequence(call_arguments: list[SemanticExpr], *, trailing_expr: SemanticExpr | None = None) -> int:
        rooted_after = 0
        max_slots = 0

        for arg in reversed(call_arguments):
            max_slots = max(max_slots, rooted_after + _max_call_temp_root_slots_in_expr(arg))
            if codegen_types.is_reference_type_name(infer_expression_type_name(arg)):
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
        return max(_max_call_temp_root_slots_in_expr(stmt.collection), _max_call_temp_root_slots_in_stmt(stmt.body))
    return 0


def build_layout(fn: SemanticFunction) -> FunctionLayout:
    if fn.body is None:
        raise ValueError("semantic layout requires a concrete function body")

    ordered_slot_names: list[str] = []
    seen_names: set[str] = set()
    local_types_by_name: dict[str, str] = {}

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

    slot_offsets = {name: -(8 * index) for index, name in enumerate(ordered_slot_names, start=1)}
    root_slot_names = [name for name in ordered_slot_names if codegen_types.is_reference_type_name(local_types_by_name[name])]
    root_slot_indices = {name: index for index, name in enumerate(root_slot_names)}

    needs_temp_runtime_roots = any(_stmt_needs_temp_runtime_roots(stmt) for stmt in fn.body.statements)
    max_call_temp_root_slots = max((_max_call_temp_root_slots_in_stmt(stmt) for stmt in fn.body.statements), default=0)
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
        root_slots_base_offset + (8 * (len(root_slot_names) + index)) for index in range(temp_root_slot_count)
    ]

    bytes_for_value_slots = len(ordered_slot_names) * 8
    bytes_for_root_slots = root_slot_count * 8
    thread_state_offset = -(bytes_for_value_slots + bytes_for_root_slots + 8)
    root_frame_offset = thread_state_offset - 24 if root_slot_count > 0 else 0

    bytes_for_thread_state = 8
    bytes_for_root_frame = 24 if root_slot_count > 0 else 0
    stack_size = _align16(bytes_for_value_slots + bytes_for_root_slots + bytes_for_thread_state + bytes_for_root_frame)

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