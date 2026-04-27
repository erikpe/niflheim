"""Straight-line scalar instruction selection for the reduced x86-64 SysV target.

Scratch register discipline for scalar x86-64 SysV emission:
- `rax` is the primary load, compute, and return register.
- `rcx` is the secondary operand register for binary instructions.
- `xmm0` is the primary floating-point load, compute, and return register.
- `xmm1` is the secondary floating-point scratch register.
- `rdx` / `dl` are reserved for float-comparison NaN handling and bit moves.
"""

from __future__ import annotations

from collections.abc import Callable
import struct

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendBlock,
    BackendBranchTerminator,
    BackendBoolConst,
    BackendCallInst,
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
    BackendUnaryInst,
)
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U8, TYPE_NAME_U64
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_PRIMARY_REGISTER = "rax"
_PRIMARY_BYTE_REGISTER = "al"
_SECONDARY_REGISTER = "rcx"
_SECONDARY_BYTE_REGISTER = "cl"
_TERTIARY_REGISTER = "rdx"
_TERTIARY_BYTE_REGISTER = "dl"
_PRIMARY_FLOAT_REGISTER = "xmm0"
_SECONDARY_FLOAT_REGISTER = "xmm1"
_UNSIGNED_TYPE_NAMES = frozenset({TYPE_NAME_U64, TYPE_NAME_U8})


def register_type_name_by_reg_id(callable_decl) -> dict:
    return {
        register.reg_id: semantic_type_canonical_name(register.type_ref)
        for register in callable_decl.registers
    }


def emit_block_instructions(
    builder: X86AsmBuilder,
    block: BackendBlock,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    call_emitter: Callable[[BackendCallInst], None] | None = None,
) -> None:
    for instruction in block.instructions:
        _emit_instruction(
            builder,
            instruction,
            block=block,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            call_emitter=call_emitter,
        )


def emit_instruction(
    builder: X86AsmBuilder,
    instruction: object,
    *,
    block: BackendBlock,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    call_emitter: Callable[[BackendCallInst], None] | None = None,
) -> None:
    _emit_instruction(
            builder,
            instruction,
            block=block,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            call_emitter=call_emitter,
        )


def emit_return_terminator(
    builder: X86AsmBuilder,
    terminator: BackendReturnTerminator,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    epilogue_label_text: str,
) -> None:
    return_type_name = None if terminator.value is None else _operand_type_name(terminator.value, register_type_name_by_reg_id)
    if terminator.value is not None:
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
                target_byte_register=_PRIMARY_BYTE_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
    builder.instruction("jmp", epilogue_label_text)


def emit_branch_terminator(
    builder: X86AsmBuilder,
    terminator: BackendBranchTerminator,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    true_label: str,
    false_label: str,
) -> None:
    emit_load_operand(
        builder,
        terminator.condition,
        target_register=_PRIMARY_REGISTER,
        target_byte_register=_PRIMARY_BYTE_REGISTER,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    builder.instruction("cmp", _PRIMARY_REGISTER, "0")
    builder.instruction("je", false_label)
    builder.instruction("jmp", true_label)


def emit_jump_terminator(builder: X86AsmBuilder, terminator: BackendJumpTerminator, *, target_label: str) -> None:
    builder.instruction("jmp", target_label)


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
    resolved_type_names = register_type_name_by_reg_id(callable_decl)
    emit_block_instructions(
        builder,
        block,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=resolved_type_names,
    )

    if not isinstance(block.terminator, BackendReturnTerminator):
        raise BackendTargetLoweringError(
            "x86_64_sysv terminator emission lands in later phase-4 slices; PR3 only supports return terminators"
        )

    emit_return_terminator(
        builder,
        block.terminator,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=resolved_type_names,
        epilogue_label_text=epilogue_label_text,
    )


def _emit_instruction(
    builder: X86AsmBuilder,
    instruction: object,
    *,
    block: BackendBlock,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    call_emitter: Callable[[BackendCallInst], None] | None = None,
) -> None:
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
        if _operand_type_name(instruction.source, register_type_name_by_reg_id) == TYPE_NAME_DOUBLE:
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
                target_byte_register=_PRIMARY_BYTE_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
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
        else:
            emit_load_operand(
                builder,
                instruction.operand,
                target_register=_PRIMARY_REGISTER,
                target_byte_register=_PRIMARY_BYTE_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
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
        else:
            emit_load_operand(
                builder,
                instruction.left,
                target_register=_PRIMARY_REGISTER,
                target_byte_register=_PRIMARY_BYTE_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            emit_load_operand(
                builder,
                instruction.right,
                target_register=_SECONDARY_REGISTER,
                target_byte_register=_SECONDARY_BYTE_REGISTER,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            _emit_binary_operation(builder, instruction, operand_type_name=operand_type_name)
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout)
        return

    if isinstance(instruction, BackendCallInst):
        if call_emitter is not None:
            call_emitter(instruction)
            return
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


def _emit_float_unary_operation(builder: X86AsmBuilder, instruction: BackendUnaryInst) -> None:
    if instruction.op.flavor == UnaryOpFlavor.FLOAT and instruction.op.kind == UnaryOpKind.NEGATE:
        builder.instruction("xorpd", _SECONDARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
        builder.instruction("subsd", _SECONDARY_FLOAT_REGISTER, _PRIMARY_FLOAT_REGISTER)
        builder.instruction("movapd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv floating unary operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
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


def _emit_float_binary_operation(builder: X86AsmBuilder, instruction: BackendBinaryInst) -> None:
    if instruction.op.flavor == BinaryOpFlavor.FLOAT:
        if instruction.op.kind == BinaryOpKind.ADD:
            builder.instruction("addsd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.SUBTRACT:
            builder.instruction("subsd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.MULTIPLY:
            builder.instruction("mulsd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        if instruction.op.kind == BinaryOpKind.DIVIDE:
            builder.instruction("divsd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
            return
        raise BackendTargetLoweringError(
            f"x86_64_sysv floating operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
        )

    if instruction.op.flavor != BinaryOpFlavor.FLOAT_COMPARISON:
        raise BackendTargetLoweringError(
            f"x86_64_sysv floating binary operator flavor '{instruction.op.flavor.value}' is not supported in the current scalar slice"
        )

    builder.instruction("ucomisd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
    if instruction.op.kind == BinaryOpKind.EQUAL:
        builder.instruction("sete", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setnp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("and", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    elif instruction.op.kind == BinaryOpKind.NOT_EQUAL:
        builder.instruction("setne", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("or", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    elif instruction.op.kind == BinaryOpKind.LESS_THAN:
        builder.instruction("setb", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setnp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("and", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    elif instruction.op.kind == BinaryOpKind.LESS_EQUAL:
        builder.instruction("setbe", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setnp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("and", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    elif instruction.op.kind == BinaryOpKind.GREATER_THAN:
        builder.instruction("seta", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setnp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("and", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    elif instruction.op.kind == BinaryOpKind.GREATER_EQUAL:
        builder.instruction("setae", _PRIMARY_BYTE_REGISTER)
        builder.instruction("setnp", _TERTIARY_BYTE_REGISTER)
        builder.instruction("and", _PRIMARY_BYTE_REGISTER, _TERTIARY_BYTE_REGISTER)
    else:
        raise BackendTargetLoweringError(
            f"x86_64_sysv floating comparison operator '{instruction.op.kind.value}' is not supported in the current scalar slice"
        )
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)


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


def emit_load_operand(
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

    if isinstance(operand, BackendDataOperand):
        raise BackendTargetLoweringError("x86_64_sysv data operands land in the later string slice")

    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot load operand '{type(operand).__name__}' in PR3"
    )


def emit_load_float_operand(
    builder: X86AsmBuilder,
    operand: BackendOperand,
    *,
    target_float_register: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    if isinstance(operand, BackendRegOperand):
        slot = frame_layout.for_reg(operand.reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv frame layout is missing a home for register 'r{operand.reg_id.ordinal}'"
            )
        if register_type_name_by_reg_id[operand.reg_id] != TYPE_NAME_DOUBLE:
            raise BackendTargetLoweringError(
                f"x86_64_sysv expected a double-typed register for floating load, got '{register_type_name_by_reg_id[operand.reg_id]}'"
            )
        builder.instruction("movq", target_float_register, format_stack_slot_operand("rbp", slot.byte_offset))
        return

    if isinstance(operand, BackendConstOperand) and isinstance(operand.constant, BackendDoubleConst):
        builder.instruction("mov", _PRIMARY_REGISTER, f"0x{_double_value_bits(operand.constant.value):016x}")
        builder.instruction("movq", target_float_register, _PRIMARY_REGISTER)
        return

    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot load floating operand '{type(operand).__name__}' in the current scalar slice"
    )


def _emit_load_constant(builder: X86AsmBuilder, constant: object, *, target_register: str) -> None:
    if isinstance(constant, BackendIntConst):
        builder.instruction("mov", target_register, str(constant.value))
        return
    if isinstance(constant, BackendBoolConst):
        builder.instruction("mov", target_register, "1" if constant.value else "0")
        return
    if isinstance(constant, BackendNullConst):
        builder.instruction("mov", target_register, "0")
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv constant '{type(constant).__name__}' is not supported in PR3 straight-line scalar mode"
    )


def emit_store_result(
    builder: X86AsmBuilder,
    dest_reg_id,
    *,
    frame_layout: X86_64SysVFrameLayout,
    source_register: str = _PRIMARY_REGISTER,
) -> None:
    slot = frame_layout.for_reg(dest_reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )
    builder.instruction("mov", format_stack_slot_operand("rbp", slot.byte_offset), source_register)


def emit_store_float_result(
    builder: X86AsmBuilder,
    dest_reg_id,
    *,
    frame_layout: X86_64SysVFrameLayout,
    source_float_register: str = _PRIMARY_FLOAT_REGISTER,
) -> None:
    slot = frame_layout.for_reg(dest_reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )
    builder.instruction("movq", format_stack_slot_operand("rbp", slot.byte_offset), source_float_register)


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
    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot infer operand type for '{type(operand).__name__}' in PR3"
    )


def _double_value_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _normalize_bool_register(builder: X86AsmBuilder, register_name: str, byte_register_name: str) -> None:
    builder.instruction("cmp", register_name, "0")
    builder.instruction("setne", byte_register_name)
    builder.instruction("movzx", register_name, byte_register_name)


def _mask_u8_result_if_needed(builder: X86AsmBuilder, operand_type_name: str) -> None:
    if operand_type_name == TYPE_NAME_U8:
        builder.instruction("and", _PRIMARY_REGISTER, "255")


__all__ = [
    "emit_block_instructions",
    "emit_branch_terminator",
    "emit_jump_terminator",
    "emit_instruction",
    "emit_load_float_operand",
    "emit_load_operand",
    "emit_return_terminator",
    "emit_store_float_result",
    "emit_store_result",
    "emit_straight_line_callable_body",
    "register_type_name_by_reg_id",
]