from __future__ import annotations

from compiler.codegen.abi.runtime import ARRAY_FROM_BYTES_U8_RUNTIME_CALL, runtime_call_metadata
from compiler.codegen.runtime_calls import runtime_dispatch_call_name
from compiler.semantic.ir import *


def expr_may_execute_gc(expr: SemanticExpr) -> bool:
    if isinstance(expr, (LiteralExprS, NullExprS, LocalRefExpr, FunctionRefExpr, ClassRefExpr)):
        return False
    if isinstance(expr, MethodRefExpr):
        return expr.receiver is not None and expr_may_execute_gc(expr.receiver)
    if isinstance(expr, (CastExprS, TypeTestExprS, UnaryExprS)):
        return expr_may_execute_gc(expr.operand)
    if isinstance(expr, BinaryExprS):
        return expr_may_execute_gc(expr.left) or expr_may_execute_gc(expr.right)
    if isinstance(expr, FieldReadExpr):
        return expr_may_execute_gc(expr.access.receiver)
    if isinstance(expr, ArrayCtorExprS):
        return True
    if isinstance(expr, StringLiteralBytesExpr):
        return runtime_call_metadata(ARRAY_FROM_BYTES_U8_RUNTIME_CALL).may_gc
    if isinstance(expr, ArrayLenExpr):
        return expr_may_execute_gc(expr.target)
    if isinstance(expr, IndexReadExpr):
        return expr_may_execute_gc(expr.target) or expr_may_execute_gc(expr.index) or _dispatch_may_execute_gc(expr.dispatch)
    if isinstance(expr, SliceReadExpr):
        return (
            expr_may_execute_gc(expr.target)
            or expr_may_execute_gc(expr.begin)
            or expr_may_execute_gc(expr.end)
            or _dispatch_may_execute_gc(expr.dispatch)
        )
    if isinstance(expr, CallExprS):
        access = call_target_receiver_access(expr.target)
        if access is not None and expr_may_execute_gc(access.receiver):
            return True
        if isinstance(expr.target, CallableValueCallTarget) and expr_may_execute_gc(expr.target.callee):
            return True
        if any(expr_may_execute_gc(arg) for arg in expr.args):
            return True
        return _call_target_may_execute_gc(expr.target)
    raise TypeError(f"Unsupported GC-effect analysis expression: {type(expr).__name__}")


def _dispatch_may_execute_gc(dispatch: SemanticDispatch) -> bool:
    if isinstance(dispatch, RuntimeDispatch):
        return runtime_call_metadata(runtime_dispatch_call_name(dispatch)).may_gc
    return True


def _call_target_may_execute_gc(target: SemanticCallTarget) -> bool:
    if isinstance(target, FunctionCallTarget):
        if target.function_id.name.startswith("rt_"):
            return runtime_call_metadata(target.function_id.name).may_gc
        return True
    if isinstance(target, (StaticMethodCallTarget, InstanceMethodCallTarget, InterfaceMethodCallTarget)):
        return True
    if isinstance(target, ConstructorCallTarget):
        return True
    if isinstance(target, CallableValueCallTarget):
        return True
    raise TypeError(f"Unsupported GC-effect analysis call target: {type(target).__name__}")