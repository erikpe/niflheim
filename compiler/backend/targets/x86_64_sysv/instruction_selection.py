"""Straight-line scalar instruction selection for the reduced x86-64 SysV target.

Scratch register discipline for phase 4 PR3:
- `rax` is the primary load, compute, and return register.
- `rcx` is the secondary operand register for binary instructions.
"""

from __future__ import annotations

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBoolConst,
    BackendCallInst,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendIntConst,
    BackendOperand,
    BackendRegOperand,
    BackendReturnTerminator,
    BackendUnaryInst,
)
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_PRIMARY_REGISTER = "rax"
_PRIMARY_BYTE_REGISTER = "al"
_SECONDARY_REGISTER = "rcx"
_SECONDARY_BYTE_REGISTER = "cl"
_UNSIGNED_TYPE_NAMES = frozenset({TYPE_NAME_U64, TYPE_NAME_U8})


def emit_straight_line_callable_body(
    builder: X86AsmBuilder,
    callable_decl,
    *,
    frame_layout: X86_64SysVFrameLayout,
    epilogue_label_text: str,
) -> None:
    if len(callable_decl.blocks) != 1 or callable_decl.entry_block_id != callable_decl.blocks[0].block_id:
        raise BackendTargetLoweringError(
            "x86_64_sysv control-flow emission lands in later phase-4 slices; PR3 only supports single-block callables"
        )

    block = callable_decl.blocks[0]
    register_type_name_by_reg_id = {
        register.reg_id: semantic_type_canonical_name(register.type_ref)
        for register in callable_decl.registers
    }

    for instruction in block.instructions:
        _emit_instruction(
            builder,
            instruction,
            block=block,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )

    if not isinstance(block.terminator, BackendReturnTerminator):
        raise BackendTargetLoweringError(
            "x86_64_sysv terminator emission lands in later phase-4 slices; PR3 only supports return terminators"
        )

    if block.terminator.value is not None:
        _emit_load_operand(
            builder,
            block.terminator.value,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
    builder.instruction("jmp", epilogue_label_text)


def _emit_instruction(
    builder: X86AsmBuilder,
    instruction: object,
    *,
    block: BackendBlock,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if isinstance(instruction, BackendConstInst):
        _emit_load_constant(builder, instruction.constant, target_register=_PRIMARY_REGISTER)
        _emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendCopyInst):
        _emit_load_operand(
            builder,
            instruction.source,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        _emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendUnaryInst):
        _emit_load_operand(
            builder,
            instruction.operand,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        operand_type_name = _operand_type_name(instruction.operand, register_type_name_by_reg_id)
        _emit_unary_operation(builder, instruction, operand_type_name=operand_type_name)
        _emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendBinaryInst):
        _emit_load_operand(
            builder,
            instruction.left,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        _emit_load_operand(
            builder,
            instruction.right,
            target_register=_SECONDARY_REGISTER,
            target_byte_register=_SECONDARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        operand_type_name = _operand_type_name(instruction.left, register_type_name_by_reg_id)
        _emit_binary_operation(builder, instruction, operand_type_name=operand_type_name)
        _emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendCallInst):
        raise BackendTargetLoweringError(
            "x86_64_sysv direct-call lowering lands in later phase-4 slices; PR3 only supports straight-line scalar instructions"
        )

    raise BackendTargetLoweringError(
        f"x86_64_sysv instruction selection does not support '{type(instruction).__name__}' in straight-line scalar mode"
    )


def _emit_unary_operation(builder: X86AsmBuilder, instruction: BackendUnaryInst, *, operand_type_name: str) -> None:
    if instruction.op.flavor == UnaryOpFlavor.INTEGER:
        if instruction.op.kind == UnaryOpKind.NEGATE:
            builder.instruction("neg", _PRIMARY_REGISTER)
            _mask_u8_result_if_needed(builder, operand_type_name)
            return
        if instruction.op.kind == UnaryOpKind.BITWISE_NOT:
            builder.instruction("not", _PRIMARY_REGISTER)
            _mask_u8_result_if_needed(builder, operand_type_name)
            return
    if instruction.op.flavor == UnaryOpFlavor.BOOL and instruction.op.kind == UnaryOpKind.LOGICAL_NOT:
        _normalize_bool_register(builder, _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
        builder.instruction("xor", _PRIMARY_REGISTER, "1")
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv unary operator '{instruction.op.kind.value}' with flavor '{instruction.op.flavor.value}' is not supported in PR3"
    )


def _emit_binary_operation(builder: X86AsmBuilder, instruction: BackendBinaryInst, *, operand_type_name: str) -> None:
    if instruction.op.flavor == BinaryOpFlavor.INTEGER:
        _emit_integer_binary_operation(builder, instruction.op.kind, operand_type_name=operand_type_name)
        return

    if instruction.op.flavor == BinaryOpFlavor.INTEGER_COMPARISON:
        _emit_integer_comparison(builder, instruction.op.kind, operand_type_name=operand_type_name)
        return

    if instruction.op.flavor == BinaryOpFlavor.BOOL_LOGICAL:
        _normalize_bool_register(builder, _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
        _normalize_bool_register(builder, _SECONDARY_REGISTER, _SECONDARY_BYTE_REGISTER)
        if instruction.op.kind == BinaryOpKind.LOGICAL_AND:
            builder.instruction("and", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.LOGICAL_OR:
            builder.instruction("or", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
            return
        raise BackendTargetLoweringError(
            f"x86_64_sysv boolean logical operator '{instruction.op.kind.value}' is not supported in PR3"
        )

    if instruction.op.flavor == BinaryOpFlavor.BOOL_COMPARISON:
        if instruction.op.kind not in {BinaryOpKind.EQUAL, BinaryOpKind.NOT_EQUAL}:
            raise BackendTargetLoweringError(
                f"x86_64_sysv boolean comparison operator '{instruction.op.kind.value}' is not supported in PR3"
            )
        _normalize_bool_register(builder, _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
        _normalize_bool_register(builder, _SECONDARY_REGISTER, _SECONDARY_BYTE_REGISTER)
        builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        builder.instruction("sete" if instruction.op.kind == BinaryOpKind.EQUAL else "setne", _PRIMARY_BYTE_REGISTER)
        builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)
        return

    raise BackendTargetLoweringError(
        f"x86_64_sysv binary operator '{instruction.op.kind.value}' with flavor '{instruction.op.flavor.value}' is not supported in PR3"
    )


def _emit_integer_binary_operation(builder: X86AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    if kind == BinaryOpKind.ADD:
        builder.instruction("add", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.SUBTRACT:
        builder.instruction("sub", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.MULTIPLY:
        builder.instruction("imul", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_AND:
        builder.instruction("and", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_OR:
        builder.instruction("or", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if kind == BinaryOpKind.BITWISE_XOR:
        builder.instruction("xor", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv integer operator '{kind.value}' is not supported in PR3"
    )


def _emit_integer_comparison(builder: X86AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
    is_unsigned = operand_type_name in _UNSIGNED_TYPE_NAMES
    if kind == BinaryOpKind.EQUAL:
        builder.instruction("sete", _PRIMARY_BYTE_REGISTER)
    elif kind == BinaryOpKind.NOT_EQUAL:
        builder.instruction("setne", _PRIMARY_BYTE_REGISTER)
    elif kind == BinaryOpKind.LESS_THAN:
        builder.instruction("setb" if is_unsigned else "setl", _PRIMARY_BYTE_REGISTER)
    elif kind == BinaryOpKind.LESS_EQUAL:
        builder.instruction("setbe" if is_unsigned else "setle", _PRIMARY_BYTE_REGISTER)
    elif kind == BinaryOpKind.GREATER_THAN:
        builder.instruction("seta" if is_unsigned else "setg", _PRIMARY_BYTE_REGISTER)
    elif kind == BinaryOpKind.GREATER_EQUAL:
        builder.instruction("setae" if is_unsigned else "setge", _PRIMARY_BYTE_REGISTER)
    else:
        raise BackendTargetLoweringError(
            f"x86_64_sysv integer comparison operator '{kind.value}' is not supported in PR3"
        )
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)


def _emit_load_operand(
    builder: X86AsmBuilder,
    operand: BackendOperand,
    *,
    target_register: str,
    target_byte_register: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if isinstance(operand, BackendRegOperand):
        slot = frame_layout.for_reg(operand.reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv frame layout is missing a home for register 'r{operand.reg_id.ordinal}'"
            )
        builder.instruction("mov", target_register, format_stack_slot_operand("rbp", slot.byte_offset))
        if register_type_name_by_reg_id[operand.reg_id] == TYPE_NAME_BOOL:
            _normalize_bool_register(builder, target_register, target_byte_register)
        return

    if isinstance(operand, BackendConstOperand):
        _emit_load_constant(builder, operand.constant, target_register=target_register)
        return

    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot load operand '{type(operand).__name__}' in PR3"
    )


def _emit_load_constant(builder: X86AsmBuilder, constant: object, *, target_register: str) -> None:
    if isinstance(constant, BackendIntConst):
        builder.instruction("mov", target_register, str(constant.value))
        return
    if isinstance(constant, BackendBoolConst):
        builder.instruction("mov", target_register, "1" if constant.value else "0")
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv constant '{type(constant).__name__}' is not supported in PR3 straight-line scalar mode"
    )


def _emit_store_result(builder: X86AsmBuilder, dest_reg_id, *, frame_layout: X86_64SysVFrameLayout) -> None:
    slot = frame_layout.for_reg(dest_reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )
    builder.instruction("mov", format_stack_slot_operand("rbp", slot.byte_offset), _PRIMARY_REGISTER)


def _operand_type_name(operand: BackendOperand, register_type_name_by_reg_id: dict) -> str:
    if isinstance(operand, BackendRegOperand):
        return register_type_name_by_reg_id[operand.reg_id]
    if isinstance(operand, BackendConstOperand):
        if isinstance(operand.constant, BackendIntConst):
            return operand.constant.type_name
        if isinstance(operand.constant, BackendBoolConst):
            return TYPE_NAME_BOOL
    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot infer operand type for '{type(operand).__name__}' in PR3"
    )


def _normalize_bool_register(builder: X86AsmBuilder, register_name: str, byte_register_name: str) -> None:
    builder.instruction("cmp", register_name, "0")
    builder.instruction("setne", byte_register_name)
    builder.instruction("movzx", register_name, byte_register_name)


def _mask_u8_result_if_needed(builder: X86AsmBuilder, operand_type_name: str) -> None:
    if operand_type_name == TYPE_NAME_U8:
        builder.instruction("and", _PRIMARY_REGISTER, "255")


__all__ = ["emit_straight_line_callable_body"]