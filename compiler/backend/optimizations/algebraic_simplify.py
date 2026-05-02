from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.backend.analysis import instruction_def_reg
from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBoolConst,
    BackendCallableDecl,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendIntConst,
    BackendOperand,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendUnaryInst,
)
from compiler.common.logging import get_logger
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, SemanticUnaryOp, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_INTEGER_MASKS = {TYPE_NAME_I64: (1 << 64) - 1, TYPE_NAME_U64: (1 << 64) - 1, TYPE_NAME_U8: (1 << 8) - 1}
_ALL_ONES_BY_TYPE = {
    TYPE_NAME_I64: -1,
    TYPE_NAME_U64: (1 << 64) - 1,
    TYPE_NAME_U8: (1 << 8) - 1,
}


@dataclass
class _AlgebraicSimplifyStats:
    simplified_instructions: int = 0
    optimized_callables: int = 0


def algebraic_simplify(program: BackendProgram) -> BackendProgram:
    logger = get_logger(__name__)
    stats = _AlgebraicSimplifyStats()
    optimized_callables = tuple(_simplify_callable(callable_decl, stats) for callable_decl in program.callables)
    optimized_program = replace(program, callables=optimized_callables)
    logger.debugv(
        1,
        "Backend optimization pass algebraic_simplify simplified %d instructions across %d callables",
        stats.simplified_instructions,
        stats.optimized_callables,
    )
    return optimized_program


def _simplify_callable(callable_decl: BackendCallableDecl, stats: _AlgebraicSimplifyStats) -> BackendCallableDecl:
    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    register_type_name_by_reg_id = {
        register.reg_id: semantic_type_canonical_name(register.type_ref) for register in callable_decl.registers
    }
    rewritten_blocks: list[BackendBlock] = []
    changed = False
    for block in callable_decl.blocks:
        rewritten_block, block_changed = _simplify_block(
            block,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            stats=stats,
        )
        rewritten_blocks.append(rewritten_block)
        changed = changed or block_changed

    if not changed:
        return callable_decl
    stats.optimized_callables += 1
    return replace(callable_decl, blocks=tuple(rewritten_blocks))


def _simplify_block(
    block: BackendBlock,
    *,
    register_type_name_by_reg_id: dict[BackendRegId, str],
    stats: _AlgebraicSimplifyStats,
) -> tuple[BackendBlock, bool]:
    unary_by_reg: dict[BackendRegId, BackendUnaryInst] = {}
    rewritten_instructions = []
    changed = False

    for instruction in block.instructions:
        simplified_instruction = _simplify_instruction(
            instruction,
            unary_by_reg=unary_by_reg,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        if simplified_instruction is not instruction:
            stats.simplified_instructions += 1
            changed = True

        destination = instruction_def_reg(simplified_instruction)
        if destination is not None:
            _invalidate_unary_facts_for_definition(unary_by_reg, destination)
        if isinstance(simplified_instruction, BackendUnaryInst):
            unary_by_reg[simplified_instruction.dest] = simplified_instruction

        rewritten_instructions.append(simplified_instruction)

    if not changed:
        return block, False
    return replace(block, instructions=tuple(rewritten_instructions)), True


def _simplify_instruction(
    instruction,
    *,
    unary_by_reg: dict[BackendRegId, BackendUnaryInst],
    register_type_name_by_reg_id: dict[BackendRegId, str],
):
    if isinstance(instruction, BackendUnaryInst):
        return _simplify_unary(instruction, unary_by_reg)
    if isinstance(instruction, BackendBinaryInst):
        return _simplify_binary(instruction, register_type_name_by_reg_id)
    return instruction


def _simplify_unary(
    instruction: BackendUnaryInst,
    unary_by_reg: dict[BackendRegId, BackendUnaryInst],
):
    if instruction.op.kind is not UnaryOpKind.LOGICAL_NOT or not isinstance(instruction.operand, BackendRegOperand):
        return instruction
    operand_def = unary_by_reg.get(instruction.operand.reg_id)
    if operand_def is None or operand_def.op.kind is not UnaryOpKind.LOGICAL_NOT:
        return instruction
    return _copy_like(instruction, operand_def.operand)


def _simplify_binary(
    instruction: BackendBinaryInst,
    register_type_name_by_reg_id: dict[BackendRegId, str],
):
    if instruction.op.flavor is BinaryOpFlavor.BOOL_LOGICAL:
        return _simplify_bool_logical(instruction)
    if instruction.op.flavor is BinaryOpFlavor.BOOL_COMPARISON:
        return _simplify_bool_comparison(instruction)
    if instruction.op.flavor is BinaryOpFlavor.INTEGER:
        return _simplify_integer(instruction, register_type_name_by_reg_id)
    return instruction


def _simplify_bool_logical(instruction: BackendBinaryInst):
    left_bool = _bool_constant_value(instruction.left)
    right_bool = _bool_constant_value(instruction.right)

    if instruction.op.kind is BinaryOpKind.LOGICAL_AND:
        if left_bool is False or right_bool is False:
            return _bool_const_like(instruction, False)
        if left_bool is True:
            return _copy_like(instruction, instruction.right)
        if right_bool is True:
            return _copy_like(instruction, instruction.left)
        return instruction

    if instruction.op.kind is BinaryOpKind.LOGICAL_OR:
        if left_bool is True or right_bool is True:
            return _bool_const_like(instruction, True)
        if left_bool is False:
            return _copy_like(instruction, instruction.right)
        if right_bool is False:
            return _copy_like(instruction, instruction.left)
        return instruction

    return instruction


def _simplify_bool_comparison(instruction: BackendBinaryInst):
    left_bool = _bool_constant_value(instruction.left)
    right_bool = _bool_constant_value(instruction.right)

    if instruction.op.kind is BinaryOpKind.EQUAL:
        if left_bool is True:
            return _copy_like(instruction, instruction.right)
        if right_bool is True:
            return _copy_like(instruction, instruction.left)
        if left_bool is False:
            return _logical_not_like(instruction, instruction.right)
        if right_bool is False:
            return _logical_not_like(instruction, instruction.left)
        return instruction

    if instruction.op.kind is BinaryOpKind.NOT_EQUAL:
        if left_bool is False:
            return _copy_like(instruction, instruction.right)
        if right_bool is False:
            return _copy_like(instruction, instruction.left)
        if left_bool is True:
            return _logical_not_like(instruction, instruction.right)
        if right_bool is True:
            return _logical_not_like(instruction, instruction.left)
        return instruction

    return instruction


def _simplify_integer(
    instruction: BackendBinaryInst,
    register_type_name_by_reg_id: dict[BackendRegId, str],
):
    left_value = _integer_constant_value(instruction.left)
    right_value = _integer_constant_value(instruction.right)
    operand_type_name = _integer_operand_type_name(instruction, register_type_name_by_reg_id)
    if operand_type_name is None:
        return instruction

    if instruction.op.kind is BinaryOpKind.ADD:
        return _simplify_identity(instruction, left_value=left_value, right_value=right_value, identity=0)
    if instruction.op.kind is BinaryOpKind.SUBTRACT:
        if right_value == 0:
            return _copy_like(instruction, instruction.left)
        return instruction
    if instruction.op.kind is BinaryOpKind.MULTIPLY:
        if left_value == 0 or right_value == 0:
            return _int_const_like(instruction, operand_type_name, 0)
        return _simplify_identity(instruction, left_value=left_value, right_value=right_value, identity=1)
    if instruction.op.kind is BinaryOpKind.DIVIDE:
        if right_value == 1:
            return _copy_like(instruction, instruction.left)
        return instruction
    if instruction.op.kind is BinaryOpKind.REMAINDER:
        if right_value == 1:
            return _int_const_like(instruction, operand_type_name, 0)
        return instruction
    if instruction.op.kind is BinaryOpKind.POWER:
        if right_value == 0:
            return _int_const_like(instruction, operand_type_name, 1)
        if right_value == 1:
            return _copy_like(instruction, instruction.left)
        return instruction
    if instruction.op.kind is BinaryOpKind.BITWISE_AND:
        if left_value == 0 or right_value == 0:
            return _int_const_like(instruction, operand_type_name, 0)
        return _simplify_identity(
            instruction,
            left_value=left_value,
            right_value=right_value,
            identity=_ALL_ONES_BY_TYPE[operand_type_name],
        )
    if instruction.op.kind is BinaryOpKind.BITWISE_OR:
        if left_value == _ALL_ONES_BY_TYPE[operand_type_name] or right_value == _ALL_ONES_BY_TYPE[operand_type_name]:
            return _int_const_like(instruction, operand_type_name, _ALL_ONES_BY_TYPE[operand_type_name])
        return _simplify_identity(instruction, left_value=left_value, right_value=right_value, identity=0)
    if instruction.op.kind is BinaryOpKind.BITWISE_XOR:
        if _same_operand(instruction.left, instruction.right):
            return _int_const_like(instruction, operand_type_name, 0)
        return _simplify_identity(instruction, left_value=left_value, right_value=right_value, identity=0)
    if instruction.op.kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
        if right_value == 0:
            return _copy_like(instruction, instruction.left)
        return instruction
    return instruction


def _simplify_identity(
    instruction: BackendBinaryInst,
    *,
    left_value: int | None,
    right_value: int | None,
    identity: int,
):
    if left_value == identity:
        return _copy_like(instruction, instruction.right)
    if right_value == identity:
        return _copy_like(instruction, instruction.left)
    return instruction


def _bool_constant_value(operand: BackendOperand) -> bool | None:
    if isinstance(operand, BackendConstOperand) and isinstance(operand.constant, BackendBoolConst):
        return operand.constant.value
    return None


def _integer_constant_value(operand: BackendOperand) -> int | None:
    if isinstance(operand, BackendConstOperand) and isinstance(operand.constant, BackendIntConst):
        return operand.constant.value
    return None


def _integer_operand_type_name(
    instruction: BackendBinaryInst,
    register_type_name_by_reg_id: dict[BackendRegId, str],
) -> str | None:
    for operand in (instruction.left, instruction.right):
        if isinstance(operand, BackendConstOperand) and isinstance(operand.constant, BackendIntConst):
            return operand.constant.type_name
        if isinstance(operand, BackendRegOperand):
            type_name = register_type_name_by_reg_id[operand.reg_id]
            if type_name in _INTEGER_MASKS:
                return type_name
    return None


def _same_operand(left: BackendOperand, right: BackendOperand) -> bool:
    return left == right


def _copy_like(instruction, source: BackendOperand) -> BackendCopyInst:
    return BackendCopyInst(inst_id=instruction.inst_id, dest=instruction.dest, source=source, span=instruction.span)


def _logical_not_like(instruction, operand: BackendOperand) -> BackendUnaryInst:
    return BackendUnaryInst(
        inst_id=instruction.inst_id,
        dest=instruction.dest,
        op=SemanticUnaryOp(kind=UnaryOpKind.LOGICAL_NOT, flavor=UnaryOpFlavor.BOOL),
        operand=operand,
        span=instruction.span,
    )


def _invalidate_unary_facts_for_definition(
    unary_by_reg: dict[BackendRegId, BackendUnaryInst],
    reg_id: BackendRegId,
) -> None:
    stale_reg_ids = [
        defined_reg_id
        for defined_reg_id, instruction in unary_by_reg.items()
        if defined_reg_id == reg_id or _operand_mentions_reg(instruction.operand, reg_id)
    ]
    for stale_reg_id in stale_reg_ids:
        del unary_by_reg[stale_reg_id]


def _operand_mentions_reg(operand: BackendOperand, reg_id: BackendRegId) -> bool:
    return isinstance(operand, BackendRegOperand) and operand.reg_id == reg_id


def _bool_const_like(instruction, value: bool) -> BackendConstInst:
    return BackendConstInst(
        inst_id=instruction.inst_id,
        dest=instruction.dest,
        constant=BackendBoolConst(value=value),
        span=instruction.span,
    )


def _int_const_like(instruction, type_name: str, value: int) -> BackendConstInst:
    return BackendConstInst(
        inst_id=instruction.inst_id,
        dest=instruction.dest,
        constant=BackendIntConst(type_name=type_name, value=_wrap_integer(value, type_name)),
        span=instruction.span,
    )


def _wrap_integer(value: int, type_name: str) -> int:
    mask = _INTEGER_MASKS[type_name]
    unsigned_value = value & mask
    if type_name == TYPE_NAME_I64:
        sign_bit = 1 << 63
        return unsigned_value if unsigned_value < sign_bit else unsigned_value - (1 << 64)
    return unsigned_value


__all__ = ["algebraic_simplify"]
