from __future__ import annotations

from compiler.semantic.ir import *
from compiler.semantic.operations import BinaryOpKind


def is_pure_expr(expr: SemanticExpr) -> bool:
    if isinstance(expr, (LocalRefExpr, FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return True
    if isinstance(expr, MethodRefExpr):
        return expr.receiver is None or is_pure_expr(expr.receiver)
    if isinstance(expr, UnaryExprS):
        return is_pure_expr(expr.operand)
    if isinstance(expr, BinaryExprS):
        if expr.op.kind in {
            BinaryOpKind.DIVIDE,
            BinaryOpKind.REMAINDER,
            BinaryOpKind.SHIFT_LEFT,
            BinaryOpKind.SHIFT_RIGHT,
        }:
            return False
        return is_pure_expr(expr.left) and is_pure_expr(expr.right)
    if isinstance(expr, CastExprS):
        return False
    if isinstance(expr, TypeTestExprS):
        return is_pure_expr(expr.operand)
    return False


def read_locals_lvalue(target: SemanticLValue) -> set[LocalId]:
    if isinstance(target, LocalLValue):
        return set()
    if isinstance(target, FieldLValue):
        return read_locals_expr(target.access.receiver)
    if isinstance(target, IndexLValue):
        return read_locals_expr(target.target) | read_locals_expr(target.index)
    if isinstance(target, SliceLValue):
        return read_locals_expr(target.target) | read_locals_expr(target.begin) | read_locals_expr(target.end)
    raise TypeError(f"Unsupported semantic lvalue local-read analysis: {type(target).__name__}")


def read_locals_expr(expr: SemanticExpr | None) -> set[LocalId]:
    if expr is None:
        return set()
    if isinstance(expr, LocalRefExpr):
        return {expr.local_id}
    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return set()
    if isinstance(expr, MethodRefExpr):
        return set() if expr.receiver is None else read_locals_expr(expr.receiver)
    if isinstance(expr, UnaryExprS):
        return read_locals_expr(expr.operand)
    if isinstance(expr, BinaryExprS):
        return read_locals_expr(expr.left) | read_locals_expr(expr.right)
    if isinstance(expr, CastExprS):
        return read_locals_expr(expr.operand)
    if isinstance(expr, TypeTestExprS):
        return read_locals_expr(expr.operand)
    if isinstance(expr, FieldReadExpr):
        return read_locals_expr(expr.access.receiver)
    if isinstance(expr, CallExprS):
        reads = set().union(*(read_locals_expr(arg) for arg in expr.args)) if expr.args else set()
        if isinstance(expr.target, CallableValueCallTarget):
            return reads | read_locals_expr(expr.target.callee)
        access = call_target_receiver_access(expr.target)
        if access is None:
            return reads
        return reads | read_locals_expr(access.receiver)
    if isinstance(expr, ArrayLenExpr):
        return read_locals_expr(expr.target)
    if isinstance(expr, IndexReadExpr):
        return read_locals_expr(expr.target) | read_locals_expr(expr.index)
    if isinstance(expr, SliceReadExpr):
        return read_locals_expr(expr.target) | read_locals_expr(expr.begin) | read_locals_expr(expr.end)
    if isinstance(expr, ArrayCtorExprS):
        return read_locals_expr(expr.length_expr)
    raise TypeError(f"Unsupported semantic expression local-read analysis: {type(expr).__name__}")
