"""Scalar instruction selection for the AArch64 backend slice-4 scaffold."""

from __future__ import annotations

import struct

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBoolConst,
    BackendCallInst,
    BackendCallableOperand,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendDataOperand,
    BackendDoubleConst,
    BackendIntConst,
    BackendJumpTerminator,
    BackendNullConst,
    BackendOperand,
    BackendRegOperand,
    BackendReturnTerminator,
    BackendBranchTerminator,
    BackendUnaryInst,
)
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.aarch64.asm import (
    AArch64AsmBuilder,
    emit_load_immediate,
    emit_materialize_symbol_address,
    format_stack_slot_operand,
    word_register_name,
)
from compiler.backend.targets.aarch64.frame import AArch64FrameLayout
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_PRIMARY_REGISTER = "x0"
_PRIMARY_WORD_REGISTER = "w0"
_SECONDARY_REGISTER = "x1"
_SECONDARY_WORD_REGISTER = "w1"
_TERTIARY_REGISTER = "x2"
_QUATERNARY_REGISTER = "x3"
_QUINARY_REGISTER = "x4"
_SENARY_REGISTER = "x5"
_PRIMARY_FLOAT_REGISTER = "d0"
_SECONDARY_FLOAT_REGISTER = "d1"
_FLOAT_TEMP_REGISTER = "d16"
_IMMEDIATE_TEMP_REGISTER = "x9"
_UNSIGNED_TYPE_NAMES = frozenset({TYPE_NAME_U64, TYPE_NAME_U8})


def register_type_name_by_reg_id(callable_decl) -> dict:
    return {
        register.reg_id: semantic_type_canonical_name(register.type_ref)
        for register in callable_decl.registers
    }


def emit_instruction(
    builder: AArch64AsmBuilder,
    instruction: object,
    *,
    block: BackendBlock,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
    call_emitter=None,
    program_symbols=None,
) -> None:
    del block
    if isinstance(instruction, BackendConstInst):
        if isinstance(instruction.constant, BackendDoubleConst):
            emit_load_float_operand(
                builder,
                BackendConstOperand(constant=instruction.constant),
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
        else:
            _emit_load_constant(builder, instruction.constant, target_register=_PRIMARY_REGISTER)
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendCopyInst):
        operand_type_name = _operand_type_name(instruction.source, register_type_name_by_reg_id)
        if operand_type_name == TYPE_NAME_DOUBLE:
            emit_load_float_operand(
                builder,
                instruction.source,
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
        else:
            emit_load_operand(
                builder,
                instruction.source,
                target_register=_PRIMARY_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
                program_symbols=program_symbols,
            )
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendUnaryInst):
        operand_type_name = _operand_type_name(instruction.operand, register_type_name_by_reg_id)
        if operand_type_name == TYPE_NAME_DOUBLE:
            emit_load_float_operand(
                builder,
                instruction.operand,
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            _emit_float_unary_operation(builder, instruction)
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        emit_load_operand(
            builder,
            instruction.operand,
            target_register=_PRIMARY_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            program_symbols=program_symbols,
        )
        _emit_unary_operation(builder, instruction, operand_type_name=operand_type_name)
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendBinaryInst):
        operand_type_name = _operand_type_name(instruction.left, register_type_name_by_reg_id)
        if operand_type_name == TYPE_NAME_DOUBLE:
            emit_load_float_operand(
                builder,
                instruction.left,
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_load_float_operand(
                builder,
                instruction.right,
                target_float_register=_SECONDARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            _emit_float_binary_operation(builder, instruction)
            if instruction.op.flavor == BinaryOpFlavor.FLOAT_COMPARISON:
                emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
            else:
                emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout)
            return
        emit_load_operand(
            builder,
            instruction.left,
            target_register=_PRIMARY_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            program_symbols=program_symbols,
        )
        emit_load_operand(
            builder,
            instruction.right,
            target_register=_SECONDARY_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            program_symbols=program_symbols,
        )
        _emit_binary_operation(builder, instruction, operand_type_name=operand_type_name)
        emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendCallInst):
        if call_emitter is None:
            raise BackendTargetLoweringError(
                "aarch64 call lowering requires the slice-4 call emitter"
            )
        call_emitter(instruction)
        return

    raise BackendTargetLoweringError(
        f"aarch64 instruction selection does not support '{type(instruction).__name__}' in slice 4"
    )


def emit_return_terminator(
    builder: AArch64AsmBuilder,
    terminator: BackendReturnTerminator,
    *,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
    epilogue_label_text: str,
    program_symbols=None,
) -> None:
    if terminator.value is not None:
        return_type_name = _operand_type_name(terminator.value, register_type_name_by_reg_id)
        if return_type_name == TYPE_NAME_DOUBLE:
            emit_load_float_operand(
                builder,
                terminator.value,
                target_float_register=_PRIMARY_FLOAT_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
        else:
            emit_load_operand(
                builder,
                terminator.value,
                target_register=_PRIMARY_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
                program_symbols=program_symbols,
            )
    builder.instruction("b", epilogue_label_text)


def emit_branch_terminator(
    builder: AArch64AsmBuilder,
    terminator: BackendBranchTerminator,
    *,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
    true_label: str,
    false_label: str,
) -> None:
    emit_load_operand(
        builder,
        terminator.condition,
        target_register=_PRIMARY_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("cmp", _PRIMARY_REGISTER, "#0")
    builder.instruction("b.eq", false_label)
    builder.instruction("b", true_label)


def emit_jump_terminator(builder: AArch64AsmBuilder, terminator: BackendJumpTerminator, *, target_label: str) -> None:
    del terminator
    builder.instruction("b", target_label)


def emit_load_operand(
    builder: AArch64AsmBuilder,
    operand: BackendOperand,
    *,
    target_register: str,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
    program_symbols=None,
) -> None:
    if isinstance(operand, BackendRegOperand):
        slot = frame_layout.for_reg(operand.reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 frame layout is missing a home for register 'r{operand.reg_id.ordinal}'"
            )
        builder.instruction("ldr", target_register, format_stack_slot_operand("x29", slot.byte_offset))
        if register_type_name_by_reg_id[operand.reg_id] == TYPE_NAME_BOOL:
            _normalize_bool_register(builder, target_register)
        return

    if isinstance(operand, BackendConstOperand):
        _emit_load_constant(builder, operand.constant, target_register=target_register)
        return

    if isinstance(operand, BackendCallableOperand):
        if program_symbols is None:
            raise BackendTargetLoweringError("aarch64 callable operands require backend program symbols")
        emit_materialize_symbol_address(
            builder,
            target_register,
            program_symbols.callable(operand.callable_id).direct_call_symbol,
        )
        return

    if isinstance(operand, BackendDataOperand):
        if program_symbols is None:
            raise BackendTargetLoweringError("aarch64 data operands require backend program symbols")
        emit_materialize_symbol_address(
            builder,
            target_register,
            program_symbols.data_blob_symbols(operand.data_id).symbol,
        )
        return

    raise BackendTargetLoweringError(
        f"aarch64 cannot load operand '{type(operand).__name__}' in slice 4"
    )


def emit_load_float_operand(
    builder: AArch64AsmBuilder,
    operand: BackendOperand,
    *,
    target_float_register: str,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if isinstance(operand, BackendRegOperand):
        slot = frame_layout.for_reg(operand.reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"aarch64 frame layout is missing a home for register 'r{operand.reg_id.ordinal}'"
            )
        if register_type_name_by_reg_id[operand.reg_id] != TYPE_NAME_DOUBLE:
            raise BackendTargetLoweringError(
                f"aarch64 expected a double-typed register for floating load, got '{register_type_name_by_reg_id[operand.reg_id]}'"
            )
        builder.instruction("ldr", target_float_register, format_stack_slot_operand("x29", slot.byte_offset))
        return

    if isinstance(operand, BackendConstOperand) and isinstance(operand.constant, BackendDoubleConst):
        emit_load_immediate(builder, _IMMEDIATE_TEMP_REGISTER, _double_value_bits(operand.constant.value))
        builder.instruction("fmov", target_float_register, _IMMEDIATE_TEMP_REGISTER)
        return

    raise BackendTargetLoweringError(
        f"aarch64 cannot load floating operand '{type(operand).__name__}' in slice 4"
    )


def emit_store_result(
    builder: AArch64AsmBuilder,
    dest_reg_id,
    *,
    frame_layout: AArch64FrameLayout,
    source_register: str = _PRIMARY_REGISTER,
) -> None:
    slot = frame_layout.for_reg(dest_reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"aarch64 frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )
    builder.instruction("str", source_register, format_stack_slot_operand("x29", slot.byte_offset))


def emit_store_float_result(
    builder: AArch64AsmBuilder,
    dest_reg_id,
    *,
    frame_layout: AArch64FrameLayout,
    source_float_register: str = _PRIMARY_FLOAT_REGISTER,
) -> None:
    slot = frame_layout.for_reg(dest_reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"aarch64 frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )
    builder.instruction("str", source_float_register, format_stack_slot_operand("x29", slot.byte_offset))


def _emit_unary_operation(builder: AArch64AsmBuilder, instruction: BackendUnaryInst, *, operand_type_name: str) -> None:
    if instruction.op.flavor == UnaryOpFlavor.INTEGER:
        if instruction.op.kind == UnaryOpKind.NEGATE:
            builder.instruction("neg", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
            _mask_u8_result_if_needed(builder, operand_type_name)
            return
        if instruction.op.kind == UnaryOpKind.BITWISE_NOT:
            builder.instruction("mvn", _PRIMARY_REGISTER, _PRIMARY_REGISTER)
            _mask_u8_result_if_needed(builder, operand_type_name)
            return
    if instruction.op.flavor == UnaryOpFlavor.BOOL and instruction.op.kind == UnaryOpKind.LOGICAL_NOT:
        _normalize_bool_register(builder, _PRIMARY_REGISTER)
        builder.instruction("eor", _PRIMARY_REGISTER, _PRIMARY_REGISTER, "#1")
        return
    raise BackendTargetLoweringError(
        f"aarch64 unary operator '{instruction.op.kind.value}' with flavor '{instruction.op.flavor.value}' is not supported in slice 4"
    )


def _emit_float_unary_operation(builder: AArch64AsmBuilder, instruction: BackendUnaryInst) -> None:
    if instruction.op.flavor == UnaryOpFlavor.FLOAT and instruction.op.kind == UnaryOpKind.NEGATE:
        builder.instruction("fneg", _PRIMARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER)
        return
    raise BackendTargetLoweringError(
        f"aarch64 floating unary operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
    )


def _emit_binary_operation(builder: AArch64AsmBuilder, instruction: BackendBinaryInst, *, operand_type_name: str) -> None:
    if instruction.op.flavor == BinaryOpFlavor.INTEGER:
        _emit_integer_binary_operation(builder, instruction.op.kind, operand_type_name=operand_type_name)
        return
    if instruction.op.flavor == BinaryOpFlavor.INTEGER_COMPARISON:
        _emit_integer_comparison(builder, instruction.op.kind, operand_type_name=operand_type_name)
        return
    if instruction.op.flavor == BinaryOpFlavor.IDENTITY_COMPARISON:
        _emit_identity_comparison(builder, instruction.op.kind)
        return
    if instruction.op.flavor == BinaryOpFlavor.BOOL_LOGICAL:
        _normalize_bool_register(builder, _PRIMARY_REGISTER)
        _normalize_bool_register(builder, _SECONDARY_REGISTER)
        if instruction.op.kind == BinaryOpKind.LOGICAL_AND:
            builder.instruction("and", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.LOGICAL_OR:
            builder.instruction("orr", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
            return
        raise BackendTargetLoweringError(
            f"aarch64 boolean logical operator '{instruction.op.kind.value}' is not supported in slice 4"
        )
    if instruction.op.flavor == BinaryOpFlavor.BOOL_COMPARISON:
        if instruction.op.kind not in {BinaryOpKind.EQUAL, BinaryOpKind.NOT_EQUAL}:
            raise BackendTargetLoweringError(
                f"aarch64 boolean comparison operator '{instruction.op.kind.value}' is not supported in slice 4"
            )
        _normalize_bool_register(builder, _PRIMARY_REGISTER)
        _normalize_bool_register(builder, _SECONDARY_REGISTER)
        builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "eq" if instruction.op.kind == BinaryOpKind.EQUAL else "ne")
        return
    raise BackendTargetLoweringError(
        f"aarch64 binary operator '{instruction.op.kind.value}' with flavor '{instruction.op.flavor.value}' is not supported in slice 4"
    )


def _emit_float_binary_operation(builder: AArch64AsmBuilder, instruction: BackendBinaryInst) -> None:
    if instruction.op.flavor == BinaryOpFlavor.FLOAT:
        if instruction.op.kind == BinaryOpKind.ADD:
            builder.instruction("fadd", _PRIMARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.SUBTRACT:
            builder.instruction("fsub", _PRIMARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.MULTIPLY:
            builder.instruction("fmul", _PRIMARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.DIVIDE:
            builder.instruction("fdiv", _PRIMARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        raise BackendTargetLoweringError(
            f"aarch64 floating operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
        )

    if instruction.op.flavor != BinaryOpFlavor.FLOAT_COMPARISON:
        raise BackendTargetLoweringError(
            f"aarch64 floating binary operator flavor '{instruction.op.flavor.value}' is not supported in the current scalar slice"
        )

    builder.instruction("fcmp", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
    if instruction.op.kind == BinaryOpKind.EQUAL:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "eq")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vc")
        builder.instruction("and", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    if instruction.op.kind == BinaryOpKind.NOT_EQUAL:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "ne")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vs")
        builder.instruction("orr", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    if instruction.op.kind == BinaryOpKind.LESS_THAN:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "lt")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vc")
        builder.instruction("and", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    if instruction.op.kind == BinaryOpKind.LESS_EQUAL:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "le")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vc")
        builder.instruction("and", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    if instruction.op.kind == BinaryOpKind.GREATER_THAN:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "gt")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vc")
        builder.instruction("and", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    if instruction.op.kind == BinaryOpKind.GREATER_EQUAL:
        builder.instruction("cset", _PRIMARY_WORD_REGISTER, "ge")
        builder.instruction("cset", _SECONDARY_WORD_REGISTER, "vc")
        builder.instruction("and", _PRIMARY_WORD_REGISTER, _PRIMARY_WORD_REGISTER, _SECONDARY_WORD_REGISTER)
        return
    raise BackendTargetLoweringError(
        f"aarch64 floating comparison operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
    )


def _emit_integer_binary_operation(builder: AArch64AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    if kind == BinaryOpKind.ADD:
        builder.instruction("add", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.SUBTRACT:
        builder.instruction("sub", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.MULTIPLY:
        builder.instruction("mul", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.POWER:
        _emit_integer_power(builder, operand_type_name=operand_type_name)
        return
    if kind == BinaryOpKind.DIVIDE:
        _emit_integer_divide_or_remainder(builder, operand_type_name=operand_type_name, emit_remainder=False)
        return
    if kind == BinaryOpKind.REMAINDER:
        _emit_integer_divide_or_remainder(builder, operand_type_name=operand_type_name, emit_remainder=True)
        return
    if kind in {BinaryOpKind.SHIFT_LEFT, BinaryOpKind.SHIFT_RIGHT}:
        _emit_integer_shift(builder, kind, operand_type_name=operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_AND:
        builder.instruction("and", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_OR:
        builder.instruction("orr", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_XOR:
        builder.instruction("eor", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    raise BackendTargetLoweringError(
        f"aarch64 integer operator '{kind.value}' is not supported in slice 4"
    )


def _emit_integer_power(builder: AArch64AsmBuilder, *, operand_type_name: str) -> None:
    emit_load_immediate(builder, _TERTIARY_REGISTER, 1)
    builder.instruction("cbz", _SECONDARY_REGISTER, "2f")
    builder.label("1")
    builder.instruction("mul", _TERTIARY_REGISTER, _TERTIARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("subs", _SECONDARY_REGISTER, _SECONDARY_REGISTER, "#1")
    builder.instruction("b.ne", "1b")
    builder.label("2")
    builder.instruction("mov", _PRIMARY_REGISTER, _TERTIARY_REGISTER)
    _mask_u8_result_if_needed(builder, operand_type_name)


def _emit_integer_divide_or_remainder(
    builder: AArch64AsmBuilder,
    *,
    operand_type_name: str,
    emit_remainder: bool,
) -> None:
    builder.instruction("cmp", _SECONDARY_REGISTER, "#0")
    builder.instruction("b.ne", "1f")
    builder.instruction("brk", "#0")
    builder.label("1")
    if operand_type_name in _UNSIGNED_TYPE_NAMES:
        builder.instruction("udiv", _TERTIARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        if emit_remainder:
            builder.instruction("msub", _PRIMARY_REGISTER, _TERTIARY_REGISTER, _SECONDARY_REGISTER, _PRIMARY_REGISTER)
        else:
            builder.instruction("mov", _PRIMARY_REGISTER, _TERTIARY_REGISTER)
            _mask_u8_result_if_needed(builder, operand_type_name)
        return

    builder.instruction("sdiv", _TERTIARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("msub", _QUATERNARY_REGISTER, _TERTIARY_REGISTER, _SECONDARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("eor", _QUINARY_REGISTER, _QUATERNARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("lsr", _QUINARY_REGISTER, _QUINARY_REGISTER, "#63")
    builder.instruction("cmp", _QUATERNARY_REGISTER, "#0")
    builder.instruction("cset", word_register_name(_SENARY_REGISTER), "ne")
    builder.instruction("and", _QUINARY_REGISTER, _QUINARY_REGISTER, _SENARY_REGISTER)
    if emit_remainder:
        builder.instruction("madd", _QUATERNARY_REGISTER, _QUINARY_REGISTER, _SECONDARY_REGISTER, _QUATERNARY_REGISTER)
        builder.instruction("mov", _PRIMARY_REGISTER, _QUATERNARY_REGISTER)
        return
    builder.instruction("sub", _TERTIARY_REGISTER, _TERTIARY_REGISTER, _QUINARY_REGISTER)
    builder.instruction("mov", _PRIMARY_REGISTER, _TERTIARY_REGISTER)


def _emit_integer_shift(builder: AArch64AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    max_shift = 8 if operand_type_name == TYPE_NAME_U8 else 64
    builder.instruction("cmp", _SECONDARY_REGISTER, f"#{max_shift}")
    builder.instruction("b.lo", "1f")
    builder.instruction("bl", "rt_panic_invalid_shift_count")
    builder.label("1")
    if kind == BinaryOpKind.SHIFT_LEFT:
        builder.instruction("lslv", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if operand_type_name in _UNSIGNED_TYPE_NAMES:
        builder.instruction("lsrv", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        return
    builder.instruction("asrv", _PRIMARY_REGISTER, _PRIMARY_REGISTER, _SECONDARY_REGISTER)


def _emit_integer_comparison(builder: AArch64AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
    is_unsigned = operand_type_name in _UNSIGNED_TYPE_NAMES
    if kind == BinaryOpKind.EQUAL:
        condition = "eq"
    elif kind == BinaryOpKind.NOT_EQUAL:
        condition = "ne"
    elif kind == BinaryOpKind.LESS_THAN:
        condition = "lo" if is_unsigned else "lt"
    elif kind == BinaryOpKind.LESS_EQUAL:
        condition = "ls" if is_unsigned else "le"
    elif kind == BinaryOpKind.GREATER_THAN:
        condition = "hi" if is_unsigned else "gt"
    elif kind == BinaryOpKind.GREATER_EQUAL:
        condition = "hs" if is_unsigned else "ge"
    else:
        raise BackendTargetLoweringError(
            f"aarch64 integer comparison operator '{kind.value}' is not supported in slice 4"
        )
    builder.instruction("cset", _PRIMARY_WORD_REGISTER, condition)


def _emit_identity_comparison(builder: AArch64AsmBuilder, kind: BinaryOpKind) -> None:
    if kind not in {BinaryOpKind.EQUAL, BinaryOpKind.NOT_EQUAL}:
        raise BackendTargetLoweringError(
            f"aarch64 identity comparison operator '{kind.value}' is not supported in slice 4"
        )
    builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("cset", _PRIMARY_WORD_REGISTER, "eq" if kind == BinaryOpKind.EQUAL else "ne")


def _emit_load_constant(builder: AArch64AsmBuilder, constant: object, *, target_register: str) -> None:
    if isinstance(constant, BackendIntConst):
        emit_load_immediate(builder, target_register, constant.value)
        return
    if isinstance(constant, BackendBoolConst):
        emit_load_immediate(builder, target_register, 1 if constant.value else 0)
        return
    if isinstance(constant, BackendNullConst):
        builder.instruction("mov", target_register, "xzr")
        return
    raise BackendTargetLoweringError(
        f"aarch64 constant '{type(constant).__name__}' is not supported in slice 4"
    )


def _operand_type_name(operand: BackendOperand, register_type_name_by_reg_id: dict) -> str:
    if isinstance(operand, BackendRegOperand):
        return register_type_name_by_reg_id[operand.reg_id]
    if isinstance(operand, BackendConstOperand):
        if isinstance(operand.constant, BackendIntConst):
            return operand.constant.type_name
        if isinstance(operand.constant, BackendBoolConst):
            return TYPE_NAME_BOOL
        if isinstance(operand.constant, BackendDoubleConst):
            return TYPE_NAME_DOUBLE
        if isinstance(operand.constant, BackendNullConst):
            return "Obj"
    if isinstance(operand, BackendCallableOperand):
        return semantic_type_canonical_name(operand.type_ref)
    raise BackendTargetLoweringError(
        f"aarch64 cannot infer operand type for '{type(operand).__name__}' in slice 4"
    )


def _normalize_bool_register(builder: AArch64AsmBuilder, register_name: str) -> None:
    builder.instruction("cmp", register_name, "#0")
    builder.instruction("cset", word_register_name(register_name), "ne")


def _mask_u8_result_if_needed(builder: AArch64AsmBuilder, operand_type_name: str) -> None:
    if operand_type_name == TYPE_NAME_U8:
        builder.instruction("and", _PRIMARY_REGISTER, _PRIMARY_REGISTER, "#255")


def _double_value_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


__all__ = [
    "emit_branch_terminator",
    "emit_instruction",
    "emit_jump_terminator",
    "emit_load_float_operand",
    "emit_load_operand",
    "emit_return_terminator",
    "emit_store_float_result",
    "emit_store_result",
    "register_type_name_by_reg_id",
]