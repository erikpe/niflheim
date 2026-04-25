"""Backend-expression lowering helpers shared by the phase-2 lowerer."""

from __future__ import annotations

from compiler.backend.ir import model as ir_model
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_UNIT
from compiler.semantic.ir import BoolConstant, CharConstant, FloatConstant, IntConstant, LiteralExprS
from compiler.semantic.types import semantic_type_canonical_name


def lower_literal_expression_to_operand(expr: LiteralExprS) -> ir_model.BackendConstOperand:
    return ir_model.BackendConstOperand(constant=lower_literal_constant(expr))


def lower_literal_constant(expr: LiteralExprS) -> ir_model.BackendConstant:
    return _lower_literal_constant(expr)


def lower_null_operand() -> ir_model.BackendConstOperand:
    return ir_model.BackendConstOperand(constant=ir_model.BackendNullConst())


def lower_unit_operand() -> ir_model.BackendConstOperand:
    return ir_model.BackendConstOperand(constant=ir_model.BackendUnitConst())


def backend_signature_return_type(type_ref):
    if semantic_type_canonical_name(type_ref) == TYPE_NAME_UNIT:
        return None
    return type_ref


def _lower_literal_constant(expr: LiteralExprS) -> ir_model.BackendConstant:
    constant = expr.constant
    canonical_name = semantic_type_canonical_name(expr.type_ref)
    if isinstance(constant, IntConstant):
        if canonical_name not in {TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8}:
            raise NotImplementedError(
                f"Backend lowering smoke path does not support integer literal type '{canonical_name}' yet"
            )
        return ir_model.BackendIntConst(type_name=canonical_name, value=constant.value)
    if isinstance(constant, CharConstant):
        return ir_model.BackendIntConst(type_name=TYPE_NAME_U8, value=constant.value)
    if isinstance(constant, BoolConstant):
        return ir_model.BackendBoolConst(value=constant.value)
    if isinstance(constant, FloatConstant):
        return ir_model.BackendDoubleConst(value=constant.value)
    raise NotImplementedError(
        f"Backend lowering smoke path does not support literal constant '{type(constant).__name__}' yet"
    )


__all__ = [
    "backend_signature_return_type",
    "lower_literal_constant",
    "lower_literal_expression_to_operand",
    "lower_null_operand",
    "lower_unit_operand",
]