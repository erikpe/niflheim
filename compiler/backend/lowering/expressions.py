"""Minimal backend-expression lowering helpers for phase-2 PR1."""

from __future__ import annotations

from compiler.backend.ir import model as ir_model
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.ir import BoolConstant, CharConstant, FloatConstant, IntConstant, LiteralExprS, LocalRefExpr, SemanticExpr
from compiler.semantic.types import semantic_type_canonical_name


def lower_smoke_expression_to_operand(
    expr: SemanticExpr,
    *,
    reg_id_by_local_id: dict,
) -> ir_model.BackendOperand:
    if isinstance(expr, LocalRefExpr):
        reg_id = reg_id_by_local_id.get(expr.local_id)
        if reg_id is None:
            raise KeyError(f"Missing backend register for semantic local {expr.local_id}")
        return ir_model.BackendRegOperand(reg_id=reg_id)
    if isinstance(expr, LiteralExprS):
        return ir_model.BackendConstOperand(constant=_lower_literal_constant(expr))
    raise NotImplementedError(
        f"Backend lowering smoke path does not support expression type '{type(expr).__name__}' yet"
    )


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


__all__ = ["lower_smoke_expression_to_operand"]