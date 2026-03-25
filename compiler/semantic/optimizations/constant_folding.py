from __future__ import annotations

import math
from dataclasses import dataclass
from dataclasses import replace

from compiler.common.logging import get_logger
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.ir import *
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, CastSemanticsKind, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_primitive_type_ref


_INTEGER_MASKS = {TYPE_NAME_I64: (1 << 64) - 1, TYPE_NAME_U64: (1 << 64) - 1, TYPE_NAME_U8: (1 << 8) - 1}

_ConstantEnv = dict[LocalId, LiteralExprS]


@dataclass
class _FoldStats:
    successful_folds: int = 0


def fold_constants(program: SemanticProgram) -> SemanticProgram:
    logger = get_logger(__name__)
    stats = _FoldStats()
    folded_program = SemanticProgram(
        entry_module=program.entry_module,
        modules={module_path: _fold_module(module, stats) for module_path, module in program.modules.items()},
    )
    logger.debugv(1, "Optimization pass constant_fold performed %d successful folds", stats.successful_folds)
    return folded_program


def _fold_module(module: SemanticModule, stats: _FoldStats) -> SemanticModule:
    return replace(
        module,
        classes=[_fold_class(cls, stats) for cls in module.classes],
        functions=[_fold_function(fn, stats) for fn in module.functions],
    )


def _fold_class(cls: SemanticClass, stats: _FoldStats) -> SemanticClass:
    return replace(
        cls,
        fields=[_fold_field(field, stats) for field in cls.fields],
        methods=[_fold_method(method, stats) for method in cls.methods],
    )


def _fold_field(field: SemanticField, stats: _FoldStats) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_fold_expr(field.initializer, {}, stats))


def _fold_function(fn: SemanticFunction, stats: _FoldStats) -> SemanticFunction:
    if fn.body is None:
        return fn
    return replace(fn, body=_fold_block(fn.body, stats=stats))


def _fold_method(method: SemanticMethod, stats: _FoldStats) -> SemanticMethod:
    return replace(method, body=_fold_block(method.body, stats=stats))


def _fold_block(block: SemanticBlock, env: _ConstantEnv | None = None, *, stats: _FoldStats) -> SemanticBlock:
    current_env = {} if env is None else env.copy()
    folded_statements: list[SemanticStmt] = []
    for stmt in block.statements:
        folded_stmt, current_env = _fold_stmt(stmt, current_env, stats)
        folded_statements.append(folded_stmt)
    return replace(block, statements=folded_statements)


def _fold_nested_block(block: SemanticBlock, env: _ConstantEnv, stats: _FoldStats) -> tuple[SemanticBlock, _ConstantEnv]:
    current_env = env.copy()
    declared_local_ids: set[LocalId] = set()
    folded_statements: list[SemanticStmt] = []

    for stmt in block.statements:
        folded_stmt, current_env = _fold_stmt(stmt, current_env, stats)
        if isinstance(stmt, SemanticVarDecl):
            declared_local_ids.add(stmt.local_id)
        folded_statements.append(folded_stmt)

    for local_id in declared_local_ids:
        current_env.pop(local_id, None)

    return replace(block, statements=folded_statements), current_env


def _fold_stmt(stmt: SemanticStmt, env: _ConstantEnv, stats: _FoldStats) -> tuple[SemanticStmt, _ConstantEnv]:
    if isinstance(stmt, SemanticBlock):
        return _fold_nested_block(stmt, env, stats)
    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _fold_expr(stmt.initializer, env, stats)
        next_env = env.copy()
        _update_local_constant(next_env, stmt.local_id, initializer)
        return replace(stmt, initializer=initializer), next_env
    if isinstance(stmt, SemanticAssign):
        target = _fold_lvalue(stmt.target, env, stats)
        value = _fold_expr(stmt.value, env, stats)
        next_env = env.copy()
        if isinstance(target, LocalLValue):
            _update_local_constant(next_env, target.local_id, value)
        return replace(stmt, target=target, value=value), next_env
    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr, env, stats)), env
    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _fold_expr(stmt.value, env, stats)
        return replace(stmt, value=value), env
    if isinstance(stmt, SemanticIf):
        return (
            replace(
                stmt,
                condition=_fold_expr(stmt.condition, env, stats),
                then_block=_fold_block(stmt.then_block, env, stats=stats),
                else_block=None if stmt.else_block is None else _fold_block(stmt.else_block, env, stats=stats),
            ),
            {},
        )
    if isinstance(stmt, SemanticWhile):
        return replace(stmt, condition=_fold_expr(stmt.condition, {}, stats), body=_fold_block(stmt.body, {}, stats=stats)), {}
    if isinstance(stmt, SemanticForIn):
        # Keep loop bodies isolated from incoming constants until this pass grows
        # a stronger model for iteration and loop-carried state.
        return replace(stmt, collection=_fold_expr(stmt.collection, env, stats), body=_fold_block(stmt.body, {}, stats=stats)), {}
    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt, env
    raise TypeError(f"Unsupported semantic statement for constant folding: {type(stmt).__name__}")


def _fold_lvalue(target: SemanticLValue, env: _ConstantEnv, stats: _FoldStats) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(target, access=replace(target.access, receiver=_fold_expr(target.access.receiver, env, stats)))
    if isinstance(target, IndexLValue):
        return replace(target, target=_fold_expr(target.target, env, stats), index=_fold_expr(target.index, env, stats))
    if isinstance(target, SliceLValue):
        return replace(
            target,
            target=_fold_expr(target.target, env, stats),
            begin=_fold_expr(target.begin, env, stats),
            end=_fold_expr(target.end, env, stats),
        )
    raise TypeError(f"Unsupported semantic lvalue for constant folding: {type(target).__name__}")


def _fold_expr(expr: SemanticExpr, env: _ConstantEnv, stats: _FoldStats) -> SemanticExpr:
    if isinstance(expr, LocalRefExpr):
        propagated = env.get(expr.local_id)
        if propagated is None or expression_type_ref(propagated) != expr.type_ref:
            return expr
        stats.successful_folds += 1
        return replace(propagated, span=expr.span)
    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, NullExprS, LiteralExprS)):
        return expr
    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _fold_expr(expr.receiver, env, stats)
        return replace(expr, receiver=receiver)
    if isinstance(expr, UnaryExprS):
        folded = replace(expr, operand=_fold_expr(expr.operand, env, stats))
        return _try_fold_unary_expr(folded, stats)
    if isinstance(expr, BinaryExprS):
        folded = replace(expr, left=_fold_expr(expr.left, env, stats), right=_fold_expr(expr.right, env, stats))
        return _try_fold_binary_expr(folded, stats)
    if isinstance(expr, CastExprS):
        folded = replace(expr, operand=_fold_expr(expr.operand, env, stats))
        return _try_fold_cast_expr(folded, stats)
    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_fold_expr(expr.operand, env, stats))
    if isinstance(expr, FieldReadExpr):
        return replace(expr, access=replace(expr.access, receiver=_fold_expr(expr.access.receiver, env, stats)))
    if isinstance(expr, CallExprS):
        folded_args = [_fold_expr(arg, env, stats) for arg in expr.args]
        if isinstance(expr.target, CallableValueCallTarget):
            return replace(expr, target=replace(expr.target, callee=_fold_expr(expr.target.callee, env, stats)), args=folded_args)
        access = call_target_receiver_access(expr.target)
        if access is None:
            return replace(expr, args=folded_args)
        return replace(
            expr,
            target=replace(expr.target, access=replace(access, receiver=_fold_expr(access.receiver, env, stats))),
            args=folded_args,
        )
    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_fold_expr(expr.target, env, stats))
    if isinstance(expr, IndexReadExpr):
        return replace(expr, target=_fold_expr(expr.target, env, stats), index=_fold_expr(expr.index, env, stats))
    if isinstance(expr, SliceReadExpr):
        return replace(
            expr,
            target=_fold_expr(expr.target, env, stats),
            begin=_fold_expr(expr.begin, env, stats),
            end=_fold_expr(expr.end, env, stats),
        )
    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_fold_expr(expr.length_expr, env, stats))
    if isinstance(expr, SyntheticExpr):
        return replace(expr, args=[_fold_expr(arg, env, stats) for arg in expr.args])
    raise TypeError(f"Unsupported semantic expression for constant folding: {type(expr).__name__}")


def _update_local_constant(env: _ConstantEnv, local_id: LocalId, value: SemanticExpr | None) -> None:
    if isinstance(value, LiteralExprS):
        env[local_id] = value
        return
    env.pop(local_id, None)


def _try_fold_unary_expr(expr: UnaryExprS, stats: _FoldStats) -> SemanticExpr:
    constant = _literal_constant(expr.operand)
    if constant is None:
        return expr

    if expr.op.kind == UnaryOpKind.LOGICAL_NOT and isinstance(constant, BoolConstant):
        stats.successful_folds += 1
        return _bool_literal_expr(not constant.value, span=expr.span)

    if expr.op.kind == UnaryOpKind.NEGATE:
        if isinstance(constant, FloatConstant):
            stats.successful_folds += 1
            return _float_literal_expr(-constant.value, span=expr.span)
        integer_value = _integer_constant_value(constant)
        if integer_value is None or expr.op.flavor != UnaryOpFlavor.INTEGER or expr.type_name != TYPE_NAME_I64:
            return expr
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(-integer_value, expr.type_name), type_name=expr.type_name, span=expr.span
        )

    if expr.op.kind == UnaryOpKind.BITWISE_NOT:
        integer_value = _integer_constant_value(constant)
        if integer_value is None or expr.type_name not in _INTEGER_MASKS:
            return expr
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(~integer_value, expr.type_name), type_name=expr.type_name, span=expr.span
        )

    return expr


def _try_fold_binary_expr(expr: BinaryExprS, stats: _FoldStats) -> SemanticExpr:
    left_constant = _literal_constant(expr.left)
    right_constant = _literal_constant(expr.right)
    if left_constant is None or right_constant is None:
        return expr

    if expr.op.flavor in {BinaryOpFlavor.BOOL_LOGICAL, BinaryOpFlavor.BOOL_COMPARISON}:
        return _fold_bool_binary_expr(expr, left_constant, right_constant, stats)

    if expr.op.flavor in {BinaryOpFlavor.FLOAT, BinaryOpFlavor.FLOAT_COMPARISON}:
        return _fold_float_binary_expr(expr, left_constant, right_constant, stats)

    left_value = _integer_constant_value(left_constant)
    right_value = _integer_constant_value(right_constant)
    if left_value is None or right_value is None:
        return expr
    operand_type_name = expression_type_name(expr.left)
    if operand_type_name not in _INTEGER_MASKS:
        return expr
    return _fold_integer_binary_expr(expr, operand_type_name, left_value, right_value, stats)


def _try_fold_cast_expr(expr: CastExprS, stats: _FoldStats) -> SemanticExpr:
    operand = expr.operand
    constant = _literal_constant(operand)
    if constant is None:
        return expr

    source_type_name = operand.type_name
    target_type_name = expr.target_type_name

    if expr.cast_kind == CastSemanticsKind.IDENTITY:
        stats.successful_folds += 1
        return replace(operand, span=expr.span)

    if expr.cast_kind == CastSemanticsKind.TO_DOUBLE:
        folded = _try_fold_cast_to_double(constant)
        if folded is None:
            return expr
        stats.successful_folds += 1
        return _float_literal_expr(folded, span=expr.span)

    if expr.cast_kind == CastSemanticsKind.TO_INTEGER:
        folded = _try_fold_cast_to_integer(constant, target_type_name)
        if folded is None:
            return expr
        stats.successful_folds += 1
        return _int_literal_expr(folded, type_name=target_type_name, span=expr.span)

    if expr.cast_kind == CastSemanticsKind.TO_BOOL:
        folded = _try_fold_cast_to_bool(constant)
        if folded is None:
            return expr
        stats.successful_folds += 1
        return _bool_literal_expr(folded, span=expr.span)

    return expr


def _fold_bool_binary_expr(
    expr: BinaryExprS, left_constant: BoolConstant, right_constant: BoolConstant, stats: _FoldStats
) -> SemanticExpr:
    if expr.op.kind == BinaryOpKind.LOGICAL_AND:
        stats.successful_folds += 1
        return _bool_literal_expr(left_constant.value and right_constant.value, span=expr.span)
    if expr.op.kind == BinaryOpKind.LOGICAL_OR:
        stats.successful_folds += 1
        return _bool_literal_expr(left_constant.value or right_constant.value, span=expr.span)
    if expr.op.kind == BinaryOpKind.EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_constant.value == right_constant.value, span=expr.span)
    if expr.op.kind == BinaryOpKind.NOT_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_constant.value != right_constant.value, span=expr.span)
    return expr


def _fold_float_binary_expr(
    expr: BinaryExprS, left_constant: FloatConstant, right_constant: FloatConstant, stats: _FoldStats
) -> SemanticExpr:
    left_value = left_constant.value
    right_value = right_constant.value

    if expr.op.kind == BinaryOpKind.ADD:
        stats.successful_folds += 1
        return _float_literal_expr(left_value + right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.SUBTRACT:
        stats.successful_folds += 1
        return _float_literal_expr(left_value - right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.MULTIPLY:
        stats.successful_folds += 1
        return _float_literal_expr(left_value * right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.DIVIDE:
        if right_value == 0.0:
            return expr
        stats.successful_folds += 1
        return _float_literal_expr(left_value / right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value == right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.NOT_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value != right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.LESS_THAN:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value < right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.LESS_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value <= right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.GREATER_THAN:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value > right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.GREATER_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value >= right_value, span=expr.span)
    return expr

def _fold_integer_binary_expr(
    expr: BinaryExprS, operand_type_name: str, left_value: int, right_value: int, stats: _FoldStats
) -> SemanticExpr:
    if expr.op.kind == BinaryOpKind.ADD:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value + right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.SUBTRACT:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value - right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.MULTIPLY:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value * right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.POWER:
        stats.successful_folds += 1
        return _int_literal_expr(
            _pow_integer(left_value, right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.DIVIDE:
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return expr
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value // right_value, operand_type_name),
            type_name=operand_type_name,
            span=expr.span,
        )
    if expr.op.kind == BinaryOpKind.REMAINDER:
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return expr
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value % right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.BITWISE_AND:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value & right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.BITWISE_OR:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value | right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind == BinaryOpKind.BITWISE_XOR:
        stats.successful_folds += 1
        return _int_literal_expr(
            _wrap_integer(left_value ^ right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.op.kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
        max_shift = 8 if operand_type_name == TYPE_NAME_U8 else 64
        if right_value >= max_shift:
            return expr
        shifted = left_value << right_value if expr.op.kind == BinaryOpKind.SHIFT_LEFT else left_value >> right_value
        stats.successful_folds += 1
        return _int_literal_expr(_wrap_integer(shifted, operand_type_name), type_name=operand_type_name, span=expr.span)
    if expr.op.kind == BinaryOpKind.EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value == right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.NOT_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value != right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.LESS_THAN:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value < right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.LESS_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value <= right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.GREATER_THAN:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value > right_value, span=expr.span)
    if expr.op.kind == BinaryOpKind.GREATER_EQUAL:
        stats.successful_folds += 1
        return _bool_literal_expr(left_value >= right_value, span=expr.span)
    return expr


def _try_fold_cast_to_double(constant) -> float | None:
    if isinstance(constant, FloatConstant):
        return constant.value
    if isinstance(constant, BoolConstant):
        return float(1 if constant.value else 0)

    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return float(integer_value)


def _try_fold_cast_to_integer(constant, target_type_name: str) -> int | None:
    if isinstance(constant, FloatConstant):
        truncated = _try_truncate_double_to_integer(constant.value, target_type_name)
        if truncated is None:
            return None
        return truncated

    if isinstance(constant, BoolConstant):
        return _wrap_integer(1 if constant.value else 0, target_type_name)

    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return _wrap_integer(integer_value, target_type_name)


def _try_fold_cast_to_bool(constant) -> bool | None:
    if isinstance(constant, BoolConstant):
        return constant.value

    if isinstance(constant, FloatConstant):
        return constant.value != 0.0

    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return integer_value != 0


def _literal_constant(expr: SemanticExpr):
    if isinstance(expr, LiteralExprS):
        return expr.constant
    return None


def _integer_constant_value(constant) -> int | None:
    if isinstance(constant, IntConstant):
        return constant.value
    if isinstance(constant, CharConstant):
        return constant.value
    return None


def _try_truncate_double_to_integer(value: float, target_type_name: str) -> int | None:
    if not math.isfinite(value):
        return None
    truncated = math.trunc(value)
    ranges = {
        TYPE_NAME_I64: (-(1 << 63), (1 << 63) - 1),
        TYPE_NAME_U64: (0, (1 << 64) - 1),
        TYPE_NAME_U8: (0, (1 << 8) - 1),
    }
    minimum, maximum = ranges[target_type_name]
    if truncated < minimum or truncated > maximum:
        return None
    return int(truncated)


def _wrap_integer(value: int, type_name: str) -> int:
    mask = _INTEGER_MASKS[type_name]
    unsigned_value = value & mask
    if type_name == TYPE_NAME_I64:
        sign_bit = 1 << 63
        return unsigned_value if unsigned_value < sign_bit else unsigned_value - (1 << 64)
    return unsigned_value


def _pow_integer(base: int, exponent: int, type_name: str) -> int:
    modulus = _INTEGER_MASKS[type_name] + 1
    folded = pow(base & (modulus - 1), exponent, modulus)
    return _wrap_integer(folded, type_name)


def _signed_division_overflows(left_value: int, right_value: int, operand_type_name: str) -> bool:
    return operand_type_name == TYPE_NAME_I64 and left_value == -(1 << 63) and right_value == -1


def _int_literal_expr(value: int, *, type_name: str, span) -> LiteralExprS:
    return LiteralExprS(
        constant=IntConstant(value=value, type_name=type_name),
        type_name=type_name,
        type_ref=semantic_primitive_type_ref(type_name),
        span=span,
    )


def _float_literal_expr(value: float, *, span) -> LiteralExprS:
    return LiteralExprS(
        constant=FloatConstant(value=value, type_name=TYPE_NAME_DOUBLE),
        type_name=TYPE_NAME_DOUBLE,
        type_ref=semantic_primitive_type_ref(TYPE_NAME_DOUBLE),
        span=span,
    )


def _bool_literal_expr(value: bool, *, span) -> LiteralExprS:
    return LiteralExprS(
        constant=BoolConstant(value=value, type_name=TYPE_NAME_BOOL),
        type_name=TYPE_NAME_BOOL,
        type_ref=semantic_primitive_type_ref(TYPE_NAME_BOOL),
        span=span,
    )
