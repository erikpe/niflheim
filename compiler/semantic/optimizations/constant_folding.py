from __future__ import annotations

import math
from dataclasses import replace

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.ir import *


_INTEGER_MASKS = {TYPE_NAME_I64: (1 << 64) - 1, TYPE_NAME_U64: (1 << 64) - 1, TYPE_NAME_U8: (1 << 8) - 1}

_ConstantEnv = dict[str, LiteralExprS]


def fold_constants(program: SemanticProgram) -> SemanticProgram:
    return SemanticProgram(
        entry_module=program.entry_module,
        modules={module_path: _fold_module(module) for module_path, module in program.modules.items()},
    )


def _fold_module(module: SemanticModule) -> SemanticModule:
    return replace(
        module,
        classes=[_fold_class(cls) for cls in module.classes],
        functions=[_fold_function(fn) for fn in module.functions],
    )


def _fold_class(cls: SemanticClass) -> SemanticClass:
    return replace(
        cls,
        fields=[_fold_field(field) for field in cls.fields],
        methods=[_fold_method(method) for method in cls.methods],
    )


def _fold_field(field: SemanticField) -> SemanticField:
    if field.initializer is None:
        return field
    return replace(field, initializer=_fold_expr(field.initializer, {}))


def _fold_function(fn: SemanticFunction) -> SemanticFunction:
    if fn.body is None:
        return fn
    return replace(fn, body=_fold_block(fn.body))


def _fold_method(method: SemanticMethod) -> SemanticMethod:
    return replace(method, body=_fold_block(method.body))


def _fold_block(block: SemanticBlock, env: _ConstantEnv | None = None) -> SemanticBlock:
    current_env = {} if env is None else env.copy()
    folded_statements: list[SemanticStmt] = []
    for stmt in block.statements:
        folded_stmt, current_env = _fold_stmt(stmt, current_env)
        folded_statements.append(folded_stmt)
    return replace(block, statements=folded_statements)


def _fold_stmt(stmt: SemanticStmt, env: _ConstantEnv) -> tuple[SemanticStmt, _ConstantEnv]:
    if isinstance(stmt, SemanticBlock):
        return _fold_block(stmt, env), env
    if isinstance(stmt, SemanticVarDecl):
        initializer = None if stmt.initializer is None else _fold_expr(stmt.initializer, env)
        next_env = env.copy()
        _update_local_constant(next_env, stmt.name, initializer)
        return replace(stmt, initializer=initializer), next_env
    if isinstance(stmt, SemanticAssign):
        target = _fold_lvalue(stmt.target, env)
        value = _fold_expr(stmt.value, env)
        next_env = env.copy()
        if isinstance(target, LocalLValue):
            _update_local_constant(next_env, target.name, value)
        return replace(stmt, target=target, value=value), next_env
    if isinstance(stmt, SemanticExprStmt):
        return replace(stmt, expr=_fold_expr(stmt.expr, env)), env
    if isinstance(stmt, SemanticReturn):
        value = None if stmt.value is None else _fold_expr(stmt.value, env)
        return replace(stmt, value=value), env
    if isinstance(stmt, SemanticIf):
        return (
            replace(
                stmt,
                condition=_fold_expr(stmt.condition, env),
                then_block=_fold_block(stmt.then_block, env),
                else_block=None if stmt.else_block is None else _fold_block(stmt.else_block, env),
            ),
            {},
        )
    if isinstance(stmt, SemanticWhile):
        return replace(stmt, condition=_fold_expr(stmt.condition, {}), body=_fold_block(stmt.body, {})), {}
    if isinstance(stmt, SemanticForIn):
        return replace(stmt, collection=_fold_expr(stmt.collection, env), body=_fold_block(stmt.body, {})), {}
    if isinstance(stmt, (SemanticBreak, SemanticContinue)):
        return stmt, env
    raise TypeError(f"Unsupported semantic statement for constant folding: {type(stmt).__name__}")


def _fold_lvalue(target: SemanticLValue, env: _ConstantEnv) -> SemanticLValue:
    if isinstance(target, LocalLValue):
        return target
    if isinstance(target, FieldLValue):
        return replace(target, receiver=_fold_expr(target.receiver, env))
    if isinstance(target, IndexLValue):
        return replace(target, target=_fold_expr(target.target, env), index=_fold_expr(target.index, env))
    if isinstance(target, SliceLValue):
        return replace(
            target,
            target=_fold_expr(target.target, env),
            begin=_fold_expr(target.begin, env),
            end=_fold_expr(target.end, env),
        )
    raise TypeError(f"Unsupported semantic lvalue for constant folding: {type(target).__name__}")


def _fold_expr(expr: SemanticExpr, env: _ConstantEnv) -> SemanticExpr:
    if isinstance(expr, LocalRefExpr):
        propagated = env.get(expr.name)
        if propagated is None or propagated.type_name != expr.type_name:
            return expr
        return replace(propagated, span=expr.span)
    if isinstance(expr, (FunctionRefExpr, ClassRefExpr, NullExprS, LiteralExprS)):
        return expr
    if isinstance(expr, MethodRefExpr):
        receiver = None if expr.receiver is None else _fold_expr(expr.receiver, env)
        return replace(expr, receiver=receiver)
    if isinstance(expr, UnaryExprS):
        folded = replace(expr, operand=_fold_expr(expr.operand, env))
        return _try_fold_unary_expr(folded)
    if isinstance(expr, BinaryExprS):
        folded = replace(expr, left=_fold_expr(expr.left, env), right=_fold_expr(expr.right, env))
        return _try_fold_binary_expr(folded)
    if isinstance(expr, CastExprS):
        folded = replace(expr, operand=_fold_expr(expr.operand, env))
        return _try_fold_cast_expr(folded)
    if isinstance(expr, TypeTestExprS):
        return replace(expr, operand=_fold_expr(expr.operand, env))
    if isinstance(expr, FieldReadExpr):
        return replace(expr, receiver=_fold_expr(expr.receiver, env))
    if isinstance(expr, FunctionCallExpr):
        return replace(expr, args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, StaticMethodCallExpr):
        return replace(expr, args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, InstanceMethodCallExpr):
        return replace(expr, receiver=_fold_expr(expr.receiver, env), args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, InterfaceMethodCallExpr):
        return replace(expr, receiver=_fold_expr(expr.receiver, env), args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, ConstructorCallExpr):
        return replace(expr, args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, CallableValueCallExpr):
        return replace(expr, callee=_fold_expr(expr.callee, env), args=[_fold_expr(arg, env) for arg in expr.args])
    if isinstance(expr, ArrayLenExpr):
        return replace(expr, target=_fold_expr(expr.target, env))
    if isinstance(expr, IndexReadExpr):
        return replace(expr, target=_fold_expr(expr.target, env), index=_fold_expr(expr.index, env))
    if isinstance(expr, SliceReadExpr):
        return replace(
            expr,
            target=_fold_expr(expr.target, env),
            begin=_fold_expr(expr.begin, env),
            end=_fold_expr(expr.end, env),
        )
    if isinstance(expr, ArrayCtorExprS):
        return replace(expr, length_expr=_fold_expr(expr.length_expr, env))
    if isinstance(expr, SyntheticExpr):
        return replace(expr, args=[_fold_expr(arg, env) for arg in expr.args])
    raise TypeError(f"Unsupported semantic expression for constant folding: {type(expr).__name__}")


def _update_local_constant(env: _ConstantEnv, name: str, value: SemanticExpr | None) -> None:
    if isinstance(value, LiteralExprS):
        env[name] = value
        return
    env.pop(name, None)


def _try_fold_unary_expr(expr: UnaryExprS) -> SemanticExpr:
    constant = _literal_constant(expr.operand)
    if constant is None:
        return expr

    if expr.operator == "!" and isinstance(constant, BoolConstant):
        return _bool_literal_expr(not constant.value, span=expr.span)

    if expr.operator == "-":
        if isinstance(constant, FloatConstant):
            return _float_literal_expr(-constant.value, span=expr.span)
        integer_value = _integer_constant_value(constant)
        if integer_value is None or expr.type_name != TYPE_NAME_I64:
            return expr
        return _int_literal_expr(
            _wrap_integer(-integer_value, expr.type_name), type_name=expr.type_name, span=expr.span
        )

    if expr.operator == "~":
        integer_value = _integer_constant_value(constant)
        if integer_value is None or expr.type_name not in _INTEGER_MASKS:
            return expr
        return _int_literal_expr(
            _wrap_integer(~integer_value, expr.type_name), type_name=expr.type_name, span=expr.span
        )

    return expr


def _try_fold_binary_expr(expr: BinaryExprS) -> SemanticExpr:
    left_constant = _literal_constant(expr.left)
    right_constant = _literal_constant(expr.right)
    if left_constant is None or right_constant is None:
        return expr

    if isinstance(left_constant, BoolConstant) and isinstance(right_constant, BoolConstant):
        return _fold_bool_binary_expr(expr, left_constant, right_constant)

    if isinstance(left_constant, FloatConstant) and isinstance(right_constant, FloatConstant):
        return _fold_float_binary_expr(expr, left_constant, right_constant)

    left_value = _integer_constant_value(left_constant)
    right_value = _integer_constant_value(right_constant)
    if left_value is None or right_value is None:
        return expr
    operand_type_name = expr.left.type_name
    if operand_type_name not in _INTEGER_MASKS:
        return expr
    return _fold_integer_binary_expr(expr, operand_type_name, left_value, right_value)


def _try_fold_cast_expr(expr: CastExprS) -> SemanticExpr:
    operand = expr.operand
    constant = _literal_constant(operand)
    if constant is None:
        return expr

    source_type_name = operand.type_name
    target_type_name = expr.target_type_name

    if source_type_name == target_type_name:
        return replace(operand, span=expr.span)

    if target_type_name == TYPE_NAME_DOUBLE:
        folded = _try_fold_cast_to_double(constant)
        if folded is None:
            return expr
        return _float_literal_expr(folded, span=expr.span)

    if target_type_name in _INTEGER_MASKS:
        folded = _try_fold_cast_to_integer(constant, target_type_name)
        if folded is None:
            return expr
        return _int_literal_expr(folded, type_name=target_type_name, span=expr.span)

    if target_type_name == TYPE_NAME_BOOL:
        folded = _try_fold_cast_to_bool(constant)
        if folded is None:
            return expr
        return _bool_literal_expr(folded, span=expr.span)

    return expr


def _fold_bool_binary_expr(
    expr: BinaryExprS, left_constant: BoolConstant, right_constant: BoolConstant
) -> SemanticExpr:
    if expr.operator == "&&":
        return _bool_literal_expr(left_constant.value and right_constant.value, span=expr.span)
    if expr.operator == "||":
        return _bool_literal_expr(left_constant.value or right_constant.value, span=expr.span)
    if expr.operator == "==":
        return _bool_literal_expr(left_constant.value == right_constant.value, span=expr.span)
    if expr.operator == "!=":
        return _bool_literal_expr(left_constant.value != right_constant.value, span=expr.span)
    return expr


def _fold_float_binary_expr(
    expr: BinaryExprS, left_constant: FloatConstant, right_constant: FloatConstant
) -> SemanticExpr:
    left_value = left_constant.value
    right_value = right_constant.value

    if expr.operator == "+":
        return _float_literal_expr(left_value + right_value, span=expr.span)
    if expr.operator == "-":
        return _float_literal_expr(left_value - right_value, span=expr.span)
    if expr.operator == "*":
        return _float_literal_expr(left_value * right_value, span=expr.span)
    if expr.operator == "/":
        if right_value == 0.0:
            return expr
        return _float_literal_expr(left_value / right_value, span=expr.span)
    if expr.operator == "==":
        return _bool_literal_expr(left_value == right_value, span=expr.span)
    if expr.operator == "!=":
        return _bool_literal_expr(left_value != right_value, span=expr.span)
    if expr.operator == "<":
        return _bool_literal_expr(left_value < right_value, span=expr.span)
    if expr.operator == "<=":
        return _bool_literal_expr(left_value <= right_value, span=expr.span)
    if expr.operator == ">":
        return _bool_literal_expr(left_value > right_value, span=expr.span)
    if expr.operator == ">=":
        return _bool_literal_expr(left_value >= right_value, span=expr.span)
    return expr


def _fold_integer_binary_expr(
    expr: BinaryExprS, operand_type_name: str, left_value: int, right_value: int
) -> SemanticExpr:
    if expr.operator == "+":
        return _int_literal_expr(
            _wrap_integer(left_value + right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "-":
        return _int_literal_expr(
            _wrap_integer(left_value - right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "*":
        return _int_literal_expr(
            _wrap_integer(left_value * right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "**":
        return _int_literal_expr(
            _pow_integer(left_value, right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "/":
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return expr
        return _int_literal_expr(
            _wrap_integer(left_value // right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "%":
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return expr
        return _int_literal_expr(
            _wrap_integer(left_value % right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "&":
        return _int_literal_expr(
            _wrap_integer(left_value & right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "|":
        return _int_literal_expr(
            _wrap_integer(left_value | right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator == "^":
        return _int_literal_expr(
            _wrap_integer(left_value ^ right_value, operand_type_name), type_name=operand_type_name, span=expr.span
        )
    if expr.operator in {"<<", ">>"}:
        max_shift = 8 if operand_type_name == TYPE_NAME_U8 else 64
        if right_value < 0 or right_value >= max_shift:
            return expr
        shifted = left_value << right_value if expr.operator == "<<" else left_value >> right_value
        return _int_literal_expr(_wrap_integer(shifted, operand_type_name), type_name=operand_type_name, span=expr.span)
    if expr.operator == "==":
        return _bool_literal_expr(left_value == right_value, span=expr.span)
    if expr.operator == "!=":
        return _bool_literal_expr(left_value != right_value, span=expr.span)
    if expr.operator == "<":
        return _bool_literal_expr(left_value < right_value, span=expr.span)
    if expr.operator == "<=":
        return _bool_literal_expr(left_value <= right_value, span=expr.span)
    if expr.operator == ">":
        return _bool_literal_expr(left_value > right_value, span=expr.span)
    if expr.operator == ">=":
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
    return LiteralExprS(constant=IntConstant(value=value, type_name=type_name), type_name=type_name, span=span)


def _float_literal_expr(value: float, *, span) -> LiteralExprS:
    return LiteralExprS(
        constant=FloatConstant(value=value, type_name=TYPE_NAME_DOUBLE), type_name=TYPE_NAME_DOUBLE, span=span
    )


def _bool_literal_expr(value: bool, *, span) -> LiteralExprS:
    return LiteralExprS(
        constant=BoolConstant(value=value, type_name=TYPE_NAME_BOOL), type_name=TYPE_NAME_BOOL, span=span
    )
