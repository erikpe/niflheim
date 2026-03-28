from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.common.logging import get_logger
from compiler.semantic.ir import *
from compiler.semantic.types import semantic_type_canonical_name


@dataclass
class _RedundantCastStats:
    removed_redundant_casts: int = 0


def redundant_cast_elimination(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _RedundantCastStats()
    optimized_program = SemanticProgram(
        entry_module=program.entry_module,
        modules={module_path: _eliminate_module(module, stats) for module_path, module in program.modules.items()},
    )
    logger.debugv(
        1, "Optimization pass redundant_cast_elimination removed %d redundant casts", stats.removed_redundant_casts
    )
    return optimized_program


def _eliminate_module(module: SemanticModule, stats: _RedundantCastStats) -> SemanticModule:
    return replace(
        module,
        classes=[_eliminate_class(cls, stats) for cls in module.classes],
        functions=[_eliminate_function(fn, stats) for fn in module.functions],
        interfaces=list(module.interfaces),
    )


def _eliminate_class(cls: SemanticClass, stats: _RedundantCastStats) -> SemanticClass:
    return replace(
        cls,
        fields=[_eliminate_field(field, stats) for field in cls.fields],
        methods=[_eliminate_method(method, stats) for method in cls.methods],
    )


def _eliminate_field(field: SemanticField, stats: _RedundantCastStats) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_eliminate_expr(field.initializer, stats))


def _eliminate_function(fn: SemanticFunction, stats: _RedundantCastStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    return replace(fn, body=_eliminate_block(fn.body, stats))


def _eliminate_method(method: SemanticMethod, stats: _RedundantCastStats) -> SemanticMethod:
    return replace(method, body=_eliminate_block(method.body, stats))


def _eliminate_block(block: SemanticBlock, stats: _RedundantCastStats) -> SemanticBlock:
    return replace(block, statements=[_eliminate_stmt(stmt, stats) for stmt in block.statements])


def _eliminate_stmt(stmt: SemanticStmt, stats: _RedundantCastStats) -> SemanticStmt:
    if isinstance(stmt, SemanticBlock):
        return _eliminate_block(stmt, stats)
    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _eliminate_expr(stmt.initializer, stats)
        return replace(stmt, initializer=initializer)
    if isinstance(stmt, SemanticAssign):
        return replace(stmt, target=_eliminate_lvalue(stmt.target, stats), value=_eliminate_expr(stmt.value, stats))
    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_eliminate_expr(stmt.expr, stats))
    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _eliminate_expr(stmt.value, stats)
        return replace(stmt, value=value)
    if isinstance(stmt, SemanticIf):
        return replace(
            stmt,
            condition=_eliminate_expr(stmt.condition, stats),
            then_block=_eliminate_block(stmt.then_block, stats),
            else_block=None if stmt.else_block is None else _eliminate_block(stmt.else_block, stats),
        )
    if isinstance(stmt, SemanticWhile):
        return replace(stmt, condition=_eliminate_expr(stmt.condition, stats), body=_eliminate_block(stmt.body, stats))
    if isinstance(stmt, SemanticForIn):
        return replace(
            stmt, collection=_eliminate_expr(stmt.collection, stats), body=_eliminate_block(stmt.body, stats)
        )
    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt
    raise TypeError(f"Unsupported semantic statement for redundant cast elimination: {type(stmt).__name__}")


def _eliminate_lvalue(target: SemanticLValue, stats: _RedundantCastStats) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(target, access=replace(target.access, receiver=_eliminate_expr(target.access.receiver, stats)))
    if isinstance(target, IndexLValue):
        return replace(target, target=_eliminate_expr(target.target, stats), index=_eliminate_expr(target.index, stats))
    if isinstance(target, SliceLValue):
        return replace(
            target,
            target=_eliminate_expr(target.target, stats),
            begin=_eliminate_expr(target.begin, stats),
            end=_eliminate_expr(target.end, stats),
        )
    raise TypeError(f"Unsupported semantic lvalue for redundant cast elimination: {type(target).__name__}")


def _eliminate_expr(expr: SemanticExpr, stats: _RedundantCastStats) -> SemanticExpr:
    if isinstance(expr, (LocalRefExpr, FunctionRefExpr, ClassRefExpr, LiteralExprS, NullExprS, StringLiteralBytesExpr)):
        return expr
    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _eliminate_expr(expr.receiver, stats)
        return replace(expr, receiver=receiver)
    if isinstance(expr, UnaryExprS):
        return replace(expr, operand=_eliminate_expr(expr.operand, stats))
    if isinstance(expr, BinaryExprS):
        return replace(expr, left=_eliminate_expr(expr.left, stats), right=_eliminate_expr(expr.right, stats))
    if isinstance(expr, CastExprS):
        simplified_operand = _eliminate_expr(expr.operand, stats)
        simplified_expr = replace(expr, operand=simplified_operand)
        if _is_redundant_cast(simplified_expr):
            stats.removed_redundant_casts += 1
            return replace(simplified_operand, type_ref=simplified_expr.type_ref, span=simplified_expr.span)
        return simplified_expr
    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_eliminate_expr(expr.operand, stats))
    if isinstance(expr, FieldReadExpr):
        return replace(expr, access=replace(expr.access, receiver=_eliminate_expr(expr.access.receiver, stats)))
    if isinstance(expr, CallExprS):
        simplified_args = [_eliminate_expr(arg, stats) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(
                expr,
                target=replace(expr.target, callee=_eliminate_expr(expr.target.callee, stats)),
                args=simplified_args,
            )
        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=simplified_args)
        return replace(
            expr,
            target=replace(expr.target, access=replace(access, receiver=_eliminate_expr(access.receiver, stats))),
            args=simplified_args,
        )
    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_eliminate_expr(expr.target, stats))
    if isinstance(expr, IndexReadExpr):
        return replace(expr, target=_eliminate_expr(expr.target, stats), index=_eliminate_expr(expr.index, stats))
    if isinstance(expr, SliceReadExpr):
        return replace(
            expr,
            target=_eliminate_expr(expr.target, stats),
            begin=_eliminate_expr(expr.begin, stats),
            end=_eliminate_expr(expr.end, stats),
        )
    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_eliminate_expr(expr.length_expr, stats))
    raise TypeError(f"Unsupported semantic expression for redundant cast elimination: {type(expr).__name__}")


def _is_redundant_cast(expr: CastExprS) -> bool:
    operand_type_name = semantic_type_canonical_name(expression_type_ref(expr.operand))
    target_type_name = semantic_type_canonical_name(expr.target_type_ref)
    return operand_type_name == target_type_name
