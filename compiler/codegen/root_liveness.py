from __future__ import annotations

from dataclasses import dataclass, field

import compiler.codegen.types as codegen_types

from compiler.semantic.lowered_ir import (
    LoweredSemanticBlock,
    LoweredSemanticConstructor,
    LoweredSemanticForIn,
    LoweredSemanticFunction,
    LoweredSemanticIf,
    LoweredSemanticMethod,
    LoweredSemanticStmt,
    LoweredSemanticWhile,
)
from compiler.semantic.ir import *


@dataclass(frozen=True)
class NamedRootLiveness:
    stmt_live_after: dict[int, frozenset[LocalId]] = field(default_factory=dict)
    expr_call_live_after: dict[int, frozenset[LocalId]] = field(default_factory=dict)
    lvalue_call_live_after: dict[int, frozenset[LocalId]] = field(default_factory=dict)
    for_in_iter_len_live_after: dict[int, frozenset[LocalId]] = field(default_factory=dict)
    for_in_iter_get_live_after: dict[int, frozenset[LocalId]] = field(default_factory=dict)

    def for_stmt(self, stmt: SemanticStmt | LoweredSemanticStmt) -> frozenset[LocalId]:
        return self.stmt_live_after.get(id(stmt), frozenset())

    def for_expr(self, expr: SemanticExpr) -> frozenset[LocalId]:
        return self.expr_call_live_after.get(id(expr), frozenset())

    def for_lvalue_call(self, target: SemanticLValue) -> frozenset[LocalId]:
        return self.lvalue_call_live_after.get(id(target), frozenset())

    def for_for_in_iter_len(self, stmt: LoweredSemanticForIn) -> frozenset[LocalId]:
        return self.for_in_iter_len_live_after.get(id(stmt), frozenset())

    def for_for_in_iter_get(self, stmt: LoweredSemanticForIn) -> frozenset[LocalId]:
        return self.for_in_iter_get_live_after.get(id(stmt), frozenset())


def analyze_named_root_liveness(
    owner: SemanticFunction
    | SemanticMethod
    | SemanticConstructor
    | LoweredSemanticFunction
    | LoweredSemanticMethod
    | LoweredSemanticConstructor,
) -> NamedRootLiveness:
    analyzer = _NamedRootLivenessAnalyzer(owner)
    return analyzer.analyze()


class _NamedRootLivenessAnalyzer:
    def __init__(
        self,
        owner: SemanticFunction
        | SemanticMethod
        | SemanticConstructor
        | LoweredSemanticFunction
        | LoweredSemanticMethod
        | LoweredSemanticConstructor,
    ) -> None:
        self.owner = owner
        self._tracked_named_roots = {
            local_info.local_id
            for local_info in owner.local_info_by_id.values()
            if codegen_types.is_reference_type_ref(local_info.type_ref)
        }
        self._stmt_live_after: dict[int, frozenset[LocalId]] = {}
        self._expr_call_live_after: dict[int, frozenset[LocalId]] = {}
        self._lvalue_call_live_after: dict[int, frozenset[LocalId]] = {}
        self._for_in_iter_len_live_after: dict[int, frozenset[LocalId]] = {}
        self._for_in_iter_get_live_after: dict[int, frozenset[LocalId]] = {}

    def analyze(self) -> NamedRootLiveness:
        body = self.owner.body
        if body is not None:
            self._analyze_block(body, live_after=set(), loop_continue_live=set(), loop_break_live=set())
        return NamedRootLiveness(
            stmt_live_after=self._stmt_live_after,
            expr_call_live_after=self._expr_call_live_after,
            lvalue_call_live_after=self._lvalue_call_live_after,
            for_in_iter_len_live_after=self._for_in_iter_len_live_after,
            for_in_iter_get_live_after=self._for_in_iter_get_live_after,
        )

    def _analyze_block(
        self,
        block: SemanticBlock | LoweredSemanticBlock,
        *,
        live_after: set[LocalId],
        loop_continue_live: set[LocalId],
        loop_break_live: set[LocalId],
    ) -> set[LocalId]:
        current = set(live_after)
        for stmt in reversed(block.statements):
            current = self._analyze_stmt(
                stmt,
                live_after=current,
                loop_continue_live=loop_continue_live,
                loop_break_live=loop_break_live,
            )
        return current

    def _analyze_stmt(
        self,
        stmt: SemanticStmt | LoweredSemanticStmt,
        *,
        live_after: set[LocalId],
        loop_continue_live: set[LocalId],
        loop_break_live: set[LocalId],
    ) -> set[LocalId]:
        self._record_stmt_live_after(stmt, live_after)
        if isinstance(stmt, (SemanticBlock, LoweredSemanticBlock)):
            return self._analyze_block(
                stmt,
                live_after=live_after,
                loop_continue_live=loop_continue_live,
                loop_break_live=loop_break_live,
            )
        if isinstance(stmt, SemanticBreak):
            return set(loop_break_live)
        if isinstance(stmt, SemanticContinue):
            return set(loop_continue_live)
        if isinstance(stmt, SemanticReturn):
            if stmt.value is None:
                return set()
            return self._analyze_expr(stmt.value, live_after=set())
        if isinstance(stmt, SemanticVarDecl):
            continuation = set(live_after)
            continuation.discard(stmt.local_id)
            if stmt.initializer is None:
                return continuation
            return self._analyze_expr(stmt.initializer, live_after=continuation)
        if isinstance(stmt, SemanticAssign):
            return self._analyze_assign(stmt, live_after=live_after)
        if isinstance(stmt, SemanticExprStmt):
            return self._analyze_expr(stmt.expr, live_after=live_after)
        if isinstance(stmt, LoweredSemanticIf):
            then_live = self._analyze_block(
                stmt.then_block,
                live_after=set(live_after),
                loop_continue_live=loop_continue_live,
                loop_break_live=loop_break_live,
            )
            else_live = set(live_after)
            if stmt.else_block is not None:
                else_live = self._analyze_block(
                    stmt.else_block,
                    live_after=set(live_after),
                    loop_continue_live=loop_continue_live,
                    loop_break_live=loop_break_live,
                )
            return self._analyze_expr(stmt.condition, live_after=then_live | else_live)
        if isinstance(stmt, LoweredSemanticWhile):
            return self._analyze_while(stmt, live_after=live_after)
        if isinstance(stmt, LoweredSemanticForIn):
            return self._analyze_for_in(stmt, live_after=live_after)
        return set(live_after)

    def _analyze_assign(self, stmt: SemanticAssign, *, live_after: set[LocalId]) -> set[LocalId]:
        target = stmt.target
        if isinstance(target, LocalLValue):
            continuation = set(live_after)
            continuation.discard(target.local_id)
            return self._analyze_expr(stmt.value, live_after=continuation)
        if isinstance(target, FieldLValue):
            after_value = self._analyze_expr(stmt.value, live_after=set(live_after))
            return self._analyze_expr(target.access.receiver, live_after=after_value)
        if isinstance(target, IndexLValue):
            self._record_lvalue_call(target, live_after)
            return self._analyze_call_arguments([target.target, target.index, stmt.value], live_after=live_after)
        if isinstance(target, SliceLValue):
            self._record_lvalue_call(target, live_after)
            return self._analyze_call_arguments(
                [target.target, target.begin, target.end, stmt.value], live_after=live_after
            )
        return set(live_after)

    def _analyze_while(self, stmt: LoweredSemanticWhile, *, live_after: set[LocalId]) -> set[LocalId]:
        loop_head_live = set(live_after)
        while True:
            body_live = self._analyze_block(
                stmt.body,
                live_after=set(loop_head_live),
                loop_continue_live=set(loop_head_live),
                loop_break_live=set(live_after),
            )
            next_head_live = self._analyze_expr(stmt.condition, live_after=body_live | set(live_after))
            if next_head_live == loop_head_live:
                return next_head_live
            loop_head_live = next_head_live

    def _analyze_for_in(self, stmt: LoweredSemanticForIn, *, live_after: set[LocalId]) -> set[LocalId]:
        if self.owner.body is None:
            return set(live_after)

        collection_ref = local_ref_expr_for_owner(self.owner, stmt.collection_local_id, span=stmt.span)
        index_ref = local_ref_expr_for_owner(self.owner, stmt.index_local_id, span=stmt.span)

        loop_head_live = set(live_after)
        while True:
            body_live = self._analyze_block(
                stmt.body,
                live_after=set(loop_head_live),
                loop_continue_live=set(loop_head_live),
                loop_break_live=set(live_after),
            )
            iter_get_live_after = set(body_live)
            iter_get_live_after.discard(stmt.element_local_id)
            self._record_for_in_iter_get(stmt, iter_get_live_after)
            iter_get_live_before = self._analyze_call_arguments(
                [collection_ref, index_ref], live_after=iter_get_live_after
            )
            next_head_live = set(live_after) | iter_get_live_before
            if next_head_live == loop_head_live:
                break
            loop_head_live = next_head_live

        iter_len_live_after = set(loop_head_live)
        self._record_for_in_iter_len(stmt, iter_len_live_after)
        iter_len_live_before = self._analyze_call_arguments([collection_ref], live_after=iter_len_live_after)

        before_collection_expr = set(iter_len_live_before)
        before_collection_expr.discard(stmt.collection_local_id)
        return self._analyze_expr(stmt.collection, live_after=before_collection_expr)

    def _analyze_expr(self, expr: SemanticExpr, *, live_after: set[LocalId]) -> set[LocalId]:
        if isinstance(expr, LocalRefExpr):
            if expr.local_id in self._tracked_named_roots:
                return set(live_after) | {expr.local_id}
            return set(live_after)
        if isinstance(expr, (FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
            if isinstance(expr, StringLiteralBytesExpr):
                self._record_expr_call(expr, live_after)
            return set(live_after)
        if isinstance(expr, MethodRefExpr):
            if expr.receiver is None:
                return set(live_after)
            return self._analyze_expr(expr.receiver, live_after=live_after)
        if isinstance(expr, UnaryExprS):
            return self._analyze_expr(expr.operand, live_after=live_after)
        if isinstance(expr, BinaryExprS):
            right_live = self._analyze_expr(expr.right, live_after=live_after)
            return self._analyze_expr(expr.left, live_after=right_live)
        if isinstance(expr, CastExprS):
            return self._analyze_expr(expr.operand, live_after=live_after)
        if isinstance(expr, TypeTestExprS):
            return self._analyze_expr(expr.operand, live_after=live_after)
        if isinstance(expr, FieldReadExpr):
            return self._analyze_expr(expr.access.receiver, live_after=live_after)
        if isinstance(expr, CallExprS):
            self._record_expr_call(expr, live_after)
            return self._analyze_call_expr(expr, live_after=live_after)
        if isinstance(expr, ArrayLenExpr):
            self._record_expr_call(expr, live_after)
            return self._analyze_call_arguments([expr.target], live_after=live_after)
        if isinstance(expr, IndexReadExpr):
            self._record_expr_call(expr, live_after)
            return self._analyze_call_arguments([expr.target, expr.index], live_after=live_after)
        if isinstance(expr, SliceReadExpr):
            self._record_expr_call(expr, live_after)
            return self._analyze_call_arguments([expr.target, expr.begin, expr.end], live_after=live_after)
        if isinstance(expr, ArrayCtorExprS):
            self._record_expr_call(expr, live_after)
            return self._analyze_expr(expr.length_expr, live_after=live_after)
        raise TypeError(f"Unsupported codegen root liveness expression analysis: {type(expr).__name__}")

    def _analyze_call_expr(self, expr: CallExprS, *, live_after: set[LocalId]) -> set[LocalId]:
        target = expr.target
        if isinstance(target, CallableValueCallTarget):
            after_callee = self._analyze_expr(target.callee, live_after=set(live_after))
            return self._analyze_call_arguments(expr.args, live_after=after_callee)
        if isinstance(target, InterfaceMethodCallTarget):
            after_args = self._analyze_call_arguments(expr.args, live_after=live_after)
            return self._analyze_expr(target.access.receiver, live_after=after_args)
        if isinstance(target, (InstanceMethodCallTarget, VirtualMethodCallTarget)):
            return self._analyze_call_arguments([target.access.receiver, *expr.args], live_after=live_after)
        return self._analyze_call_arguments(expr.args, live_after=live_after)

    def _analyze_call_arguments(self, call_arguments: list[SemanticExpr], *, live_after: set[LocalId]) -> set[LocalId]:
        current = set(live_after)
        for arg in call_arguments:
            current = self._analyze_expr(arg, live_after=current)
        return current

    def _record_expr_call(self, expr: SemanticExpr, live_after: set[LocalId]) -> None:
        self._expr_call_live_after[id(expr)] = self._existing_union(self._expr_call_live_after.get(id(expr)), live_after)

    def _record_stmt_live_after(self, stmt: SemanticStmt | LoweredSemanticStmt, live_after: set[LocalId]) -> None:
        self._stmt_live_after[id(stmt)] = self._existing_union(self._stmt_live_after.get(id(stmt)), live_after)

    def _record_lvalue_call(self, target: SemanticLValue, live_after: set[LocalId]) -> None:
        self._lvalue_call_live_after[id(target)] = self._existing_union(
            self._lvalue_call_live_after.get(id(target)), live_after
        )

    def _record_for_in_iter_len(self, stmt: LoweredSemanticForIn, live_after: set[LocalId]) -> None:
        self._for_in_iter_len_live_after[id(stmt)] = self._existing_union(
            self._for_in_iter_len_live_after.get(id(stmt)), live_after
        )

    def _record_for_in_iter_get(self, stmt: LoweredSemanticForIn, live_after: set[LocalId]) -> None:
        self._for_in_iter_get_live_after[id(stmt)] = self._existing_union(
            self._for_in_iter_get_live_after.get(id(stmt)), live_after
        )

    def _existing_union(self, existing: frozenset[LocalId] | None, live_after: set[LocalId]) -> frozenset[LocalId]:
        tracked_live_after = frozenset(local_id for local_id in live_after if local_id in self._tracked_named_roots)
        if existing is None:
            return tracked_live_after
        return existing | tracked_live_after