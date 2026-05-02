from __future__ import annotations

import math
from dataclasses import dataclass, replace

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBoolConst,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendCastInst,
    BackendConstInst,
    BackendConstOperand,
    BackendConstant,
    BackendCopyInst,
    BackendDoubleConst,
    BackendIntConst,
    BackendJumpTerminator,
    BackendNullConst,
    BackendOperand,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendReturnTerminator,
    BackendTerminator,
    BackendUnaryInst,
    BackendUnitConst,
)
from compiler.backend.analysis import index_callable_cfg, instruction_def_reg
from compiler.common.logging import get_logger
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, CastSemanticsKind, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_INTEGER_MASKS = {TYPE_NAME_I64: (1 << 64) - 1, TYPE_NAME_U64: (1 << 64) - 1, TYPE_NAME_U8: (1 << 8) - 1}


@dataclass
class _ConstantFoldStats:
    folded_instructions: int = 0
    propagated_operands: int = 0
    optimized_callables: int = 0


def constant_fold(program: BackendProgram) -> BackendProgram:
    logger = get_logger(__name__)
    stats = _ConstantFoldStats()
    optimized_callables = tuple(_fold_callable(callable_decl, stats) for callable_decl in program.callables)
    optimized_program = replace(program, callables=optimized_callables)
    logger.debugv(
        1,
        "Backend optimization pass constant_fold folded %d instructions, propagated %d operands across %d callables",
        stats.folded_instructions,
        stats.propagated_operands,
        stats.optimized_callables,
    )
    return optimized_program


def _fold_callable(callable_decl: BackendCallableDecl, stats: _ConstantFoldStats) -> BackendCallableDecl:
    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    register_type_name_by_reg_id = {
        register.reg_id: semantic_type_canonical_name(register.type_ref)
        for register in callable_decl.registers
    }
    incoming_constants_by_block = _incoming_constants_by_block(callable_decl, register_type_name_by_reg_id)
    rewritten_blocks: list[BackendBlock] = []
    changed = False
    for block in callable_decl.blocks:
        rewritten_block, block_changed = _fold_block(
            block,
            initial_constant_by_reg=incoming_constants_by_block.get(block.block_id, {}),
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            stats=stats,
        )
        rewritten_blocks.append(rewritten_block)
        changed = changed or block_changed

    if not changed:
        return callable_decl
    stats.optimized_callables += 1
    return replace(callable_decl, blocks=tuple(rewritten_blocks))


def _fold_block(
    block: BackendBlock,
    *,
    initial_constant_by_reg: dict[BackendRegId, BackendConstant],
    register_type_name_by_reg_id: dict[BackendRegId, str],
    stats: _ConstantFoldStats,
) -> tuple[BackendBlock, bool]:
    constant_by_reg = dict(initial_constant_by_reg)
    rewritten_instructions = []
    changed = False

    for instruction in block.instructions:
        destination = instruction_def_reg(instruction)
        if destination is not None:
            constant_by_reg.pop(destination, None)

        folded_instruction = _try_fold_instruction(instruction, constant_by_reg, register_type_name_by_reg_id)
        if folded_instruction is not instruction:
            stats.folded_instructions += 1
            changed = True
            instruction = folded_instruction
        else:
            rewritten_instruction, propagated_count = _rewrite_instruction_operands(instruction, constant_by_reg)
            if propagated_count:
                stats.propagated_operands += propagated_count
                changed = True
                instruction = rewritten_instruction

        if isinstance(instruction, BackendConstInst):
            constant_by_reg[instruction.dest] = instruction.constant
        rewritten_instructions.append(instruction)

    rewritten_terminator, propagated_count = _rewrite_terminator_operands(block.terminator, constant_by_reg)
    if propagated_count:
        stats.propagated_operands += propagated_count
        changed = True

    if not changed:
        return block, False
    return replace(block, instructions=tuple(rewritten_instructions), terminator=rewritten_terminator), True


def _try_fold_instruction(
    instruction,
    constant_by_reg: dict[BackendRegId, BackendConstant],
    register_type_name_by_reg_id: dict[BackendRegId, str],
):
    if isinstance(instruction, BackendCopyInst):
        source = _resolve_constant(instruction.source, constant_by_reg)
        if source is None:
            return instruction
        return _const_like(instruction, source)

    if isinstance(instruction, BackendUnaryInst):
        operand = _resolve_constant(instruction.operand, constant_by_reg)
        if operand is None:
            return instruction
        folded = _fold_unary(instruction, operand)
        return instruction if folded is None else _const_like(instruction, folded)

    if isinstance(instruction, BackendBinaryInst):
        left = _resolve_constant(instruction.left, constant_by_reg)
        right = _resolve_constant(instruction.right, constant_by_reg)
        if left is None or right is None:
            return instruction
        dest_type_name = register_type_name_by_reg_id[instruction.dest]
        folded = _fold_binary(instruction, left, right, dest_type_name=dest_type_name)
        return instruction if folded is None else _const_like(instruction, folded)

    if isinstance(instruction, BackendCastInst):
        operand = _resolve_constant(instruction.operand, constant_by_reg)
        if operand is None:
            return instruction
        folded = _fold_cast(instruction, operand)
        return instruction if folded is None else _const_like(instruction, folded)

    return instruction


def _incoming_constants_by_block(
    callable_decl: BackendCallableDecl,
    register_type_name_by_reg_id: dict[BackendRegId, str],
) -> dict:
    cfg = index_callable_cfg(callable_decl)
    in_by_block = {block_id: {} for block_id in cfg.block_by_id}
    out_by_block = {block_id: {} for block_id in cfg.block_by_id}

    changed = True
    while changed:
        changed = False
        for block_id in cfg.reverse_postorder_block_ids:
            if block_id == callable_decl.entry_block_id:
                incoming = {}
            else:
                incoming = _intersect_constant_maps(
                    tuple(out_by_block[predecessor_id] for predecessor_id in cfg.predecessor_by_block[block_id])
                )
            outgoing = _transfer_block_constants(
                cfg.block_by_id[block_id],
                incoming,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            if in_by_block[block_id] != incoming:
                in_by_block[block_id] = incoming
                changed = True
            if out_by_block[block_id] != outgoing:
                out_by_block[block_id] = outgoing
                changed = True
    return in_by_block


def _transfer_block_constants(
    block: BackendBlock,
    incoming: dict[BackendRegId, BackendConstant],
    *,
    register_type_name_by_reg_id: dict[BackendRegId, str],
) -> dict[BackendRegId, BackendConstant]:
    constant_by_reg = dict(incoming)
    for instruction in block.instructions:
        destination = instruction_def_reg(instruction)
        if destination is not None:
            constant_by_reg.pop(destination, None)
        folded_instruction = _try_fold_instruction(instruction, constant_by_reg, register_type_name_by_reg_id)
        if isinstance(folded_instruction, BackendConstInst):
            constant_by_reg[folded_instruction.dest] = folded_instruction.constant
        elif isinstance(instruction, BackendConstInst):
            constant_by_reg[instruction.dest] = instruction.constant
    return constant_by_reg


def _intersect_constant_maps(maps: tuple[dict[BackendRegId, BackendConstant], ...]) -> dict[BackendRegId, BackendConstant]:
    if not maps:
        return {}
    common_reg_ids = set(maps[0])
    for constant_map in maps[1:]:
        common_reg_ids.intersection_update(constant_map)
    return {
        reg_id: maps[0][reg_id]
        for reg_id in common_reg_ids
        if all(constant_map[reg_id] == maps[0][reg_id] for constant_map in maps[1:])
    }


def _const_like(instruction, constant: BackendConstant) -> BackendConstInst:
    return BackendConstInst(inst_id=instruction.inst_id, dest=instruction.dest, constant=constant, span=instruction.span)


def _fold_unary(instruction: BackendUnaryInst, constant: BackendConstant) -> BackendConstant | None:
    if instruction.op.kind is UnaryOpKind.LOGICAL_NOT and isinstance(constant, BackendBoolConst):
        return BackendBoolConst(value=not constant.value)

    if instruction.op.kind is UnaryOpKind.NEGATE:
        if isinstance(constant, BackendDoubleConst):
            return BackendDoubleConst(value=-constant.value)
        integer_value = _integer_constant_value(constant)
        if integer_value is None or constant.type_name != TYPE_NAME_I64:
            return None
        return BackendIntConst(type_name=constant.type_name, value=_wrap_integer(-integer_value, constant.type_name))

    if instruction.op.kind is UnaryOpKind.BITWISE_NOT:
        integer_value = _integer_constant_value(constant)
        if integer_value is None or constant.type_name not in _INTEGER_MASKS:
            return None
        return BackendIntConst(type_name=constant.type_name, value=_wrap_integer(~integer_value, constant.type_name))

    return None


def _fold_binary(
    instruction: BackendBinaryInst,
    left: BackendConstant,
    right: BackendConstant,
    *,
    dest_type_name: str,
) -> BackendConstant | None:
    if instruction.op.flavor in {BinaryOpFlavor.BOOL_LOGICAL, BinaryOpFlavor.BOOL_COMPARISON}:
        if not isinstance(left, BackendBoolConst) or not isinstance(right, BackendBoolConst):
            return None
        return _fold_bool_binary(instruction.op.kind, left.value, right.value)

    if instruction.op.flavor in {BinaryOpFlavor.FLOAT, BinaryOpFlavor.FLOAT_COMPARISON}:
        if not isinstance(left, BackendDoubleConst) or not isinstance(right, BackendDoubleConst):
            return None
        return _fold_float_binary(instruction.op.kind, left.value, right.value)

    left_value = _integer_constant_value(left)
    right_value = _integer_constant_value(right)
    if left_value is None or right_value is None:
        return None
    operand_type_name = left.type_name
    if operand_type_name not in _INTEGER_MASKS:
        return None
    return _fold_integer_binary(instruction.op.kind, operand_type_name, left_value, right_value, dest_type_name)


def _fold_bool_binary(kind: BinaryOpKind, left_value: bool, right_value: bool) -> BackendConstant | None:
    if kind is BinaryOpKind.LOGICAL_AND:
        return BackendBoolConst(value=left_value and right_value)
    if kind is BinaryOpKind.LOGICAL_OR:
        return BackendBoolConst(value=left_value or right_value)
    if kind is BinaryOpKind.EQUAL:
        return BackendBoolConst(value=left_value == right_value)
    if kind is BinaryOpKind.NOT_EQUAL:
        return BackendBoolConst(value=left_value != right_value)
    return None


def _fold_float_binary(kind: BinaryOpKind, left_value: float, right_value: float) -> BackendConstant | None:
    if kind is BinaryOpKind.ADD:
        return BackendDoubleConst(value=left_value + right_value)
    if kind is BinaryOpKind.SUBTRACT:
        return BackendDoubleConst(value=left_value - right_value)
    if kind is BinaryOpKind.MULTIPLY:
        return BackendDoubleConst(value=left_value * right_value)
    if kind is BinaryOpKind.DIVIDE:
        if right_value == 0.0:
            return None
        return BackendDoubleConst(value=left_value / right_value)
    if kind is BinaryOpKind.EQUAL:
        return BackendBoolConst(value=left_value == right_value)
    if kind is BinaryOpKind.NOT_EQUAL:
        return BackendBoolConst(value=left_value != right_value)
    if kind is BinaryOpKind.LESS_THAN:
        return BackendBoolConst(value=left_value < right_value)
    if kind is BinaryOpKind.LESS_EQUAL:
        return BackendBoolConst(value=left_value <= right_value)
    if kind is BinaryOpKind.GREATER_THAN:
        return BackendBoolConst(value=left_value > right_value)
    if kind is BinaryOpKind.GREATER_EQUAL:
        return BackendBoolConst(value=left_value >= right_value)
    return None


def _fold_integer_binary(
    kind: BinaryOpKind,
    operand_type_name: str,
    left_value: int,
    right_value: int,
    dest_type_name: str,
) -> BackendConstant | None:
    if kind is BinaryOpKind.ADD:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value + right_value, operand_type_name))
    if kind is BinaryOpKind.SUBTRACT:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value - right_value, operand_type_name))
    if kind is BinaryOpKind.MULTIPLY:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value * right_value, operand_type_name))
    if kind is BinaryOpKind.POWER:
        if right_value < 0:
            return None
        return BackendIntConst(type_name=operand_type_name, value=_pow_integer(left_value, right_value, operand_type_name))
    if kind is BinaryOpKind.DIVIDE:
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return None
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value // right_value, operand_type_name))
    if kind is BinaryOpKind.REMAINDER:
        if right_value == 0 or _signed_division_overflows(left_value, right_value, operand_type_name):
            return None
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value % right_value, operand_type_name))
    if kind is BinaryOpKind.BITWISE_AND:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value & right_value, operand_type_name))
    if kind is BinaryOpKind.BITWISE_OR:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value | right_value, operand_type_name))
    if kind is BinaryOpKind.BITWISE_XOR:
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(left_value ^ right_value, operand_type_name))
    if kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
        max_shift = 8 if operand_type_name == TYPE_NAME_U8 else 64
        if right_value < 0 or right_value >= max_shift:
            return None
        shifted = left_value << right_value if kind is BinaryOpKind.SHIFT_LEFT else left_value >> right_value
        return BackendIntConst(type_name=operand_type_name, value=_wrap_integer(shifted, operand_type_name))
    if kind is BinaryOpKind.EQUAL:
        return BackendBoolConst(value=left_value == right_value)
    if kind is BinaryOpKind.NOT_EQUAL:
        return BackendBoolConst(value=left_value != right_value)
    if kind is BinaryOpKind.LESS_THAN:
        return BackendBoolConst(value=left_value < right_value)
    if kind is BinaryOpKind.LESS_EQUAL:
        return BackendBoolConst(value=left_value <= right_value)
    if kind is BinaryOpKind.GREATER_THAN:
        return BackendBoolConst(value=left_value > right_value)
    if kind is BinaryOpKind.GREATER_EQUAL:
        return BackendBoolConst(value=left_value >= right_value)
    return None


def _fold_cast(instruction: BackendCastInst, constant: BackendConstant) -> BackendConstant | None:
    if instruction.trap_on_failure:
        return None

    target_type_name = semantic_type_canonical_name(instruction.target_type_ref)

    if instruction.cast_kind is CastSemanticsKind.IDENTITY:
        return constant
    if instruction.cast_kind is CastSemanticsKind.TO_DOUBLE:
        folded = _try_fold_cast_to_double(constant)
        return None if folded is None else BackendDoubleConst(value=folded)
    if instruction.cast_kind is CastSemanticsKind.TO_INTEGER:
        folded = _try_fold_cast_to_integer(constant, target_type_name)
        return None if folded is None else BackendIntConst(type_name=target_type_name, value=folded)
    if instruction.cast_kind is CastSemanticsKind.TO_BOOL:
        folded = _try_fold_cast_to_bool(constant)
        return None if folded is None else BackendBoolConst(value=folded)
    return None


def _rewrite_instruction_operands(
    instruction,
    constant_by_reg: dict[BackendRegId, BackendConstant],
) -> tuple[object, int]:
    if isinstance(instruction, BackendUnaryInst):
        operand, count = _rewrite_operand(instruction.operand, constant_by_reg)
        return replace(instruction, operand=operand), count
    if isinstance(instruction, BackendBinaryInst):
        left, left_count = _rewrite_operand(instruction.left, constant_by_reg)
        right, right_count = _rewrite_operand(instruction.right, constant_by_reg)
        return replace(instruction, left=left, right=right), left_count + right_count
    if isinstance(instruction, BackendCastInst):
        operand, count = _rewrite_operand(instruction.operand, constant_by_reg)
        return replace(instruction, operand=operand), count
    return instruction, 0


def _rewrite_terminator_operands(
    terminator: BackendTerminator,
    constant_by_reg: dict[BackendRegId, BackendConstant],
) -> tuple[BackendTerminator, int]:
    if isinstance(terminator, BackendBranchTerminator):
        condition, count = _rewrite_operand(terminator.condition, constant_by_reg)
        return replace(terminator, condition=condition), count
    if isinstance(terminator, BackendReturnTerminator) and terminator.value is not None:
        value, count = _rewrite_operand(terminator.value, constant_by_reg)
        return replace(terminator, value=value), count
    if isinstance(terminator, BackendJumpTerminator):
        return terminator, 0
    return terminator, 0


def _rewrite_operand(
    operand: BackendOperand,
    constant_by_reg: dict[BackendRegId, BackendConstant],
) -> tuple[BackendOperand, int]:
    if isinstance(operand, BackendRegOperand) and operand.reg_id in constant_by_reg:
        return BackendConstOperand(constant=constant_by_reg[operand.reg_id]), 1
    return operand, 0


def _resolve_constant(
    operand: BackendOperand,
    constant_by_reg: dict[BackendRegId, BackendConstant],
) -> BackendConstant | None:
    if isinstance(operand, BackendConstOperand):
        return operand.constant
    if isinstance(operand, BackendRegOperand):
        return constant_by_reg.get(operand.reg_id)
    return None


def _integer_constant_value(constant: BackendConstant) -> int | None:
    if isinstance(constant, BackendIntConst):
        return constant.value
    return None


def _try_fold_cast_to_double(constant: BackendConstant) -> float | None:
    if isinstance(constant, BackendDoubleConst):
        return constant.value
    if isinstance(constant, BackendBoolConst):
        return float(1 if constant.value else 0)
    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return float(integer_value)


def _try_fold_cast_to_integer(constant: BackendConstant, target_type_name: str) -> int | None:
    if target_type_name not in _INTEGER_MASKS:
        return None
    if isinstance(constant, BackendDoubleConst):
        truncated = _try_truncate_double_to_integer(constant.value, target_type_name)
        if truncated is None:
            return None
        return truncated
    if isinstance(constant, BackendBoolConst):
        return _wrap_integer(1 if constant.value else 0, target_type_name)
    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return _wrap_integer(integer_value, target_type_name)


def _try_fold_cast_to_bool(constant: BackendConstant) -> bool | None:
    if isinstance(constant, BackendBoolConst):
        return constant.value
    if isinstance(constant, BackendDoubleConst):
        return constant.value != 0.0
    integer_value = _integer_constant_value(constant)
    if integer_value is None:
        return None
    return integer_value != 0


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


__all__ = ["constant_fold"]
