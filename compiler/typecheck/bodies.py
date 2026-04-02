from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_UNIT
from compiler.frontend.ast_nodes import (
    AssignStmt,
    BinaryExpr,
    BlockStmt,
    BreakStmt,
    CastExpr,
    ContinueStmt,
    Expression,
    ExprStmt,
    FieldAccessExpr,
    ForInStmt,
    IdentifierExpr,
    IfStmt,
    LiteralExpr,
    NullExpr,
    ReturnStmt,
    Statement,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.expressions import infer_expression_type
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.relations import require_assignable
from compiler.typecheck.statements import check_function_like as statements_check_function_like


def _check_constant_field_initializer(expr: Expression) -> None:
    if isinstance(expr, (LiteralExpr, NullExpr)):
        return
    if isinstance(expr, UnaryExpr):
        _check_constant_field_initializer(expr.operand)
        return
    if isinstance(expr, BinaryExpr):
        _check_constant_field_initializer(expr.left)
        _check_constant_field_initializer(expr.right)
        return
    if isinstance(expr, CastExpr):
        _check_constant_field_initializer(expr.operand)
        return
    raise TypeCheckError("Class field initializer must be a constant expression in MVP", expr.span)


def _check_class_field_initializers(ctx: TypeCheckContext) -> None:
    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        for field_decl in class_decl.fields:
            if field_decl.initializer is None:
                continue
            _check_constant_field_initializer(field_decl.initializer)
            init_type = infer_expression_type(ctx, field_decl.initializer)
            field_type = class_info.fields[field_decl.name]
            require_assignable(ctx, field_type, init_type, field_decl.initializer.span)


@dataclass(frozen=True)
class _ConstructorInitState:
    definitely_assigned: frozenset[str]
    maybe_assigned: frozenset[str]


@dataclass(frozen=True)
class _ConstructorFlowResult:
    normal: _ConstructorInitState | None
    break_states: tuple[_ConstructorInitState, ...] = ()
    continue_states: tuple[_ConstructorInitState, ...] = ()


def _merge_constructor_states(states: list[_ConstructorInitState]) -> _ConstructorInitState | None:
    if not states:
        return None

    definitely_assigned = set(states[0].definitely_assigned)
    maybe_assigned: set[str] = set()
    for state in states:
        definitely_assigned &= state.definitely_assigned
        maybe_assigned |= state.maybe_assigned
    return _ConstructorInitState(
        definitely_assigned=frozenset(definitely_assigned),
        maybe_assigned=frozenset(maybe_assigned),
    )


def _constructor_missing_field_message(class_name: str, missing_fields: set[str]) -> str:
    missing = sorted(missing_fields)
    if len(missing) == 1:
        return f"Constructor for class '{class_name}' does not initialize field '{missing[0]}'"
    return f"Constructor for class '{class_name}' does not initialize fields: {', '.join(missing)}"


def _validate_constructor_required_fields(
    *,
    class_name: str,
    required_fields: set[str],
    state: _ConstructorInitState,
    span,
) -> None:
    missing_fields = required_fields - set(state.definitely_assigned)
    if missing_fields:
        raise TypeCheckError(_constructor_missing_field_message(class_name, missing_fields), span)


def _constructor_assigned_self_field_name(stmt: AssignStmt) -> str | None:
    if not isinstance(stmt.target, FieldAccessExpr):
        return None
    if not isinstance(stmt.target.object_expr, IdentifierExpr):
        return None
    if stmt.target.object_expr.name != "__self":
        return None
    return stmt.target.field_name


def _assign_constructor_field(
    *,
    class_name: str,
    field_name: str,
    final_fields: set[str],
    state: _ConstructorInitState,
    span,
) -> _ConstructorInitState:
    if field_name in final_fields and field_name in state.maybe_assigned:
        raise TypeCheckError(f"Final field '{class_name}.{field_name}' may be assigned multiple times in constructor", span)

    return _ConstructorInitState(
        definitely_assigned=state.definitely_assigned | {field_name},
        maybe_assigned=state.maybe_assigned | {field_name},
    )


def _analyze_constructor_block(
    block: BlockStmt,
    state: _ConstructorInitState,
    *,
    class_name: str,
    required_fields: set[str],
    final_fields: set[str],
) -> _ConstructorFlowResult:
    current_state: _ConstructorInitState | None = state
    break_states: list[_ConstructorInitState] = []
    continue_states: list[_ConstructorInitState] = []

    for stmt in block.statements:
        if current_state is None:
            break
        stmt_result = _analyze_constructor_statement(
            stmt,
            current_state,
            class_name=class_name,
            required_fields=required_fields,
            final_fields=final_fields,
        )
        current_state = stmt_result.normal
        break_states.extend(stmt_result.break_states)
        continue_states.extend(stmt_result.continue_states)

    return _ConstructorFlowResult(
        normal=current_state,
        break_states=tuple(break_states),
        continue_states=tuple(continue_states),
    )


def _analyze_constructor_statement(
    stmt: Statement,
    state: _ConstructorInitState,
    *,
    class_name: str,
    required_fields: set[str],
    final_fields: set[str],
) -> _ConstructorFlowResult:
    if isinstance(stmt, BlockStmt):
        return _analyze_constructor_block(
            stmt,
            state,
            class_name=class_name,
            required_fields=required_fields,
            final_fields=final_fields,
        )

    if isinstance(stmt, VarDeclStmt | ExprStmt):
        return _ConstructorFlowResult(normal=state)

    if isinstance(stmt, ReturnStmt):
        _validate_constructor_required_fields(
            class_name=class_name,
            required_fields=required_fields,
            state=state,
            span=stmt.span,
        )
        return _ConstructorFlowResult(normal=None)

    if isinstance(stmt, AssignStmt):
        field_name = _constructor_assigned_self_field_name(stmt)
        if field_name is None:
            return _ConstructorFlowResult(normal=state)
        return _ConstructorFlowResult(
            normal=_assign_constructor_field(
                class_name=class_name,
                field_name=field_name,
                final_fields=final_fields,
                state=state,
                span=stmt.span,
            )
        )

    if isinstance(stmt, IfStmt):
        then_result = _analyze_constructor_block(
            stmt.then_branch,
            state,
            class_name=class_name,
            required_fields=required_fields,
            final_fields=final_fields,
        )
        if isinstance(stmt.else_branch, BlockStmt):
            else_result = _analyze_constructor_block(
                stmt.else_branch,
                state,
                class_name=class_name,
                required_fields=required_fields,
                final_fields=final_fields,
            )
        elif isinstance(stmt.else_branch, IfStmt):
            else_result = _analyze_constructor_statement(
                stmt.else_branch,
                state,
                class_name=class_name,
                required_fields=required_fields,
                final_fields=final_fields,
            )
        else:
            else_result = _ConstructorFlowResult(normal=state)

        merged_normal = _merge_constructor_states(
            [branch_state for branch_state in (then_result.normal, else_result.normal) if branch_state is not None]
        )
        return _ConstructorFlowResult(
            normal=merged_normal,
            break_states=then_result.break_states + else_result.break_states,
            continue_states=then_result.continue_states + else_result.continue_states,
        )

    if isinstance(stmt, BreakStmt):
        return _ConstructorFlowResult(normal=None, break_states=(state,))

    if isinstance(stmt, ContinueStmt):
        return _ConstructorFlowResult(normal=None, continue_states=(state,))

    if isinstance(stmt, WhileStmt | ForInStmt):
        body = stmt.body
        body_result = _analyze_constructor_block(
            body,
            state,
            class_name=class_name,
            required_fields=required_fields,
            final_fields=final_fields,
        )

        repeated_iteration_states = [loop_state for loop_state in (body_result.normal, *body_result.continue_states) if loop_state is not None]
        if repeated_iteration_states:
            repeated_maybe_assigned = set().union(*(loop_state.maybe_assigned for loop_state in repeated_iteration_states))
            repeated_final_fields = (repeated_maybe_assigned - set(state.maybe_assigned)) & final_fields
            if repeated_final_fields:
                field_name = sorted(repeated_final_fields)[0]
                raise TypeCheckError(
                    f"Final field '{class_name}.{field_name}' may be assigned multiple times in constructor",
                    stmt.span,
                )

        continuation_maybe_assigned = set(state.maybe_assigned)
        for loop_state in (*body_result.break_states, *repeated_iteration_states):
            continuation_maybe_assigned |= set(loop_state.maybe_assigned)

        return _ConstructorFlowResult(
            normal=_ConstructorInitState(
                definitely_assigned=state.definitely_assigned,
                maybe_assigned=frozenset(continuation_maybe_assigned),
            )
        )

    return _ConstructorFlowResult(normal=state)


def _check_constructor_field_initialization(ctx: TypeCheckContext) -> None:
    for class_decl in ctx.module_ast.classes:
        if not class_decl.constructors:
            continue

        class_info = ctx.classes[class_decl.name]
        initialized_by_default = {
            field_decl.name for field_decl in class_decl.fields if field_decl.initializer is not None
        }
        required_fields = {
            field_decl.name for field_decl in class_decl.fields if field_decl.initializer is None
        }
        initial_state = _ConstructorInitState(
            definitely_assigned=frozenset(initialized_by_default),
            maybe_assigned=frozenset(initialized_by_default),
        )

        for constructor_decl in class_decl.constructors:
            constructor_result = _analyze_constructor_block(
                constructor_decl.body,
                initial_state,
                class_name=class_decl.name,
                required_fields=required_fields,
                final_fields=class_info.final_fields,
            )
            if constructor_result.normal is not None:
                _validate_constructor_required_fields(
                    class_name=class_decl.name,
                    required_fields=required_fields,
                    state=constructor_result.normal,
                    span=constructor_decl.span,
                )


def check_bodies(ctx: TypeCheckContext) -> None:
    _check_class_field_initializers(ctx)

    for fn_decl in ctx.module_ast.functions:
        if fn_decl.is_extern:
            continue
        fn_sig = ctx.functions[fn_decl.name]
        body = fn_decl.body
        assert body is not None
        statements_check_function_like(ctx, fn_decl.params, body, fn_sig.return_type)

    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        for constructor_decl in class_decl.constructors:
            statements_check_function_like(
                ctx,
                constructor_decl.params,
                constructor_decl.body,
                TypeInfo(name=TYPE_NAME_UNIT, kind="primitive"),
                receiver_type=TypeInfo(name=class_info.name, kind="reference"),
                owner_class_name=class_info.name,
                allow_value_return=False,
                allow_final_field_assignment=True,
            )

    _check_constructor_field_initialization(ctx)

    for class_decl in ctx.module_ast.classes:
        class_info = ctx.classes[class_decl.name]
        for method_decl in class_decl.methods:
            method_sig = class_info.methods[method_decl.name]
            statements_check_function_like(
                ctx,
                method_decl.params,
                method_decl.body,
                method_sig.return_type,
                receiver_type=None if method_sig.is_static else TypeInfo(name=class_info.name, kind="reference"),
                owner_class_name=class_info.name,
            )
