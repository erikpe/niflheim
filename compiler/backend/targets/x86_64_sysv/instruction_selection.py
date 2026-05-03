"""Straight-line scalar instruction selection for the reduced x86-64 SysV target.

Scratch register discipline for scalar x86-64 SysV emission:
- `rax` is the primary load, compute, and return register.
- `rcx` is the secondary operand register for binary instructions.
- `r8` / `r9` are transient scratch registers for integer divide and remainder fixups.
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
    BackendCastInst,
    BackendConstInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendDataOperand,
    BackendDoubleConst,
    BackendCallableOperand,
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
from compiler.semantic.operations import BinaryOpFlavor, BinaryOpKind, CastSemanticsKind, UnaryOpFlavor, UnaryOpKind
from compiler.semantic.types import semantic_type_canonical_name


_PRIMARY_REGISTER = "rax"
_PRIMARY_BYTE_REGISTER = "al"
_SECONDARY_REGISTER = "rcx"
_SECONDARY_BYTE_REGISTER = "cl"
_TERTIARY_REGISTER = "rdx"
_TERTIARY_BYTE_REGISTER = "dl"
_QUATERNARY_REGISTER = "r8"
_QUINARY_REGISTER = "r9"
_QUINARY_BYTE_REGISTER = "r9b"
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
    program_symbols=None,
) -> None:
    _emit_instruction(
            builder,
            instruction,
            block=block,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            call_emitter=call_emitter,
            program_symbols=program_symbols,
        )


def emit_return_terminator(
    builder: X86AsmBuilder,
    terminator: BackendReturnTerminator,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    epilogue_label_text: str,
    program_symbols=None,
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
                program_symbols=program_symbols,
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
    program_symbols=None,
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
            if _try_emit_direct_scalar_copy(
                builder,
                instruction.source,
                instruction.dest,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
                program_symbols=program_symbols,
            ):
                return
            emit_load_operand(
                builder,
                instruction.source,
                target_register=_PRIMARY_REGISTER,
                target_byte_register=_PRIMARY_BYTE_REGISTER,
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
        else:
            if _try_emit_direct_integer_unary(
                builder,
                instruction,
                operand_type_name=operand_type_name,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            ):
                return
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
            if _try_emit_direct_integer_binary(
                builder,
                instruction,
                operand_type_name=operand_type_name,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            ):
                return
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

    if isinstance(instruction, BackendCastInst):
        emit_load_operand(
            builder,
            instruction.operand,
            target_register=_PRIMARY_REGISTER,
            target_byte_register=_PRIMARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        _emit_scalar_cast(builder, instruction, source_type_name=_operand_type_name(instruction.operand, register_type_name_by_reg_id))
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
        builder.instruction("movabs", _TERTIARY_REGISTER, "0x8000000000000000")
        builder.instruction("movq", _SECONDARY_FLOAT_REGISTER, _TERTIARY_REGISTER)
        builder.instruction("xorpd", _PRIMARY_FLOAT_REGISTER, _SECONDARY_FLOAT_REGISTER)
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

    if instruction.op.flavor == BinaryOpFlavor.IDENTITY_COMPARISON:
        _emit_identity_comparison(builder, instruction.op.kind)
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


def _try_emit_direct_integer_unary(
    builder: X86AsmBuilder,
    instruction: BackendUnaryInst,
    *,
    operand_type_name: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> bool:
    if instruction.op.flavor != UnaryOpFlavor.INTEGER:
        return False
    if instruction.op.kind not in {UnaryOpKind.NEGATE, UnaryOpKind.BITWISE_NOT}:
        return False

    dest_register = _physical_register_name_for_dest(frame_layout, instruction.dest)
    if dest_register is None:
        return False

    _emit_load_scalar_operand_into_register(
        builder,
        instruction.operand,
        target_register=dest_register,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    if instruction.op.kind == UnaryOpKind.NEGATE:
        builder.instruction("neg", dest_register)
    else:
        builder.instruction("not", dest_register)
    _mask_u8_result_if_needed(builder, operand_type_name, target_register=dest_register)
    return True


def _try_emit_direct_integer_binary(
    builder: X86AsmBuilder,
    instruction: BackendBinaryInst,
    *,
    operand_type_name: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> bool:
    if instruction.op.flavor != BinaryOpFlavor.INTEGER:
        return False

    op_mnemonic = _direct_integer_binary_mnemonic(instruction.op.kind)
    if op_mnemonic is None:
        return False

    dest_register = _physical_register_name_for_dest(frame_layout, instruction.dest)
    if dest_register is None:
        return False

    left_operand = instruction.left
    right_operand = instruction.right
    if _operation_is_commutative(instruction.op.kind) and _operand_physical_register_name(frame_layout, right_operand) == dest_register:
        left_operand, right_operand = right_operand, left_operand
    elif (
        not _operation_is_commutative(instruction.op.kind)
        and _operand_physical_register_name(frame_layout, right_operand) == dest_register
        and _operand_physical_register_name(frame_layout, left_operand) != dest_register
    ):
        return False

    _emit_load_scalar_operand_into_register(
        builder,
        left_operand,
        target_register=dest_register,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )
    right_asm_operand = _scalar_asm_operand_for_binary_rhs(
        right_operand,
        frame_layout=frame_layout,
        allow_immediate=instruction.op.kind is not BinaryOpKind.MULTIPLY,
    )
    if right_asm_operand is None:
        emit_load_operand(
            builder,
            right_operand,
            target_register=_SECONDARY_REGISTER,
            target_byte_register=_SECONDARY_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        right_asm_operand = _SECONDARY_REGISTER

    builder.instruction(op_mnemonic, dest_register, right_asm_operand)
    _mask_u8_result_if_needed(builder, operand_type_name, target_register=dest_register)
    return True


def _direct_integer_binary_mnemonic(kind: BinaryOpKind) -> str | None:
    return {
        BinaryOpKind.ADD: "add",
        BinaryOpKind.SUBTRACT: "sub",
        BinaryOpKind.MULTIPLY: "imul",
        BinaryOpKind.BITWISE_AND: "and",
        BinaryOpKind.BITWISE_OR: "or",
        BinaryOpKind.BITWISE_XOR: "xor",
    }.get(kind)


def _operation_is_commutative(kind: BinaryOpKind) -> bool:
    return kind in {
        BinaryOpKind.ADD,
        BinaryOpKind.MULTIPLY,
        BinaryOpKind.BITWISE_AND,
        BinaryOpKind.BITWISE_OR,
        BinaryOpKind.BITWISE_XOR,
    }


def _emit_integer_power(builder: X86AsmBuilder, *, operand_type_name: str) -> None:
    builder.instruction("mov", _QUATERNARY_REGISTER, "1")
    builder.instruction("test", _SECONDARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("jz", "2f")
    builder.label("1")
    builder.instruction("imul", _QUATERNARY_REGISTER, _PRIMARY_REGISTER)
    builder.instruction("dec", _SECONDARY_REGISTER)
    builder.instruction("jnz", "1b")
    builder.label("2")
    builder.instruction("mov", _PRIMARY_REGISTER, _QUATERNARY_REGISTER)
    _mask_u8_result_if_needed(builder, operand_type_name)


def _emit_integer_divide_or_remainder(
    builder: X86AsmBuilder, *, operand_type_name: str, emit_remainder: bool
) -> None:
    if operand_type_name in _UNSIGNED_TYPE_NAMES:
        builder.instruction("xor", _TERTIARY_REGISTER, _TERTIARY_REGISTER)
        builder.instruction("div", _SECONDARY_REGISTER)
        if emit_remainder:
            builder.instruction("mov", _PRIMARY_REGISTER, _TERTIARY_REGISTER)
        else:
            _mask_u8_result_if_needed(builder, operand_type_name)
        return

    builder.instruction("cqo")
    builder.instruction("idiv", _SECONDARY_REGISTER)
    builder.instruction("mov", _QUATERNARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("xor", _QUATERNARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("shr", _QUATERNARY_REGISTER, "63")
    builder.instruction("test", _TERTIARY_REGISTER, _TERTIARY_REGISTER)
    builder.instruction("setne", _QUINARY_BYTE_REGISTER)
    builder.instruction("movzx", _QUINARY_REGISTER, _QUINARY_BYTE_REGISTER)
    builder.instruction("and", _QUATERNARY_REGISTER, _QUINARY_REGISTER)
    if emit_remainder:
        builder.instruction("imul", _QUATERNARY_REGISTER, _SECONDARY_REGISTER)
        builder.instruction("add", _TERTIARY_REGISTER, _QUATERNARY_REGISTER)
        builder.instruction("mov", _PRIMARY_REGISTER, _TERTIARY_REGISTER)
        return
    builder.instruction("sub", _PRIMARY_REGISTER, _QUATERNARY_REGISTER)


def _emit_integer_shift(builder: X86AsmBuilder, kind: BinaryOpKind, *, operand_type_name: str) -> None:
    max_shift = "8" if operand_type_name == TYPE_NAME_U8 else "64"
    builder.instruction("cmp", _SECONDARY_REGISTER, max_shift)
    builder.instruction("jb", "1f")
    builder.instruction("call", "rt_panic_invalid_shift_count")
    builder.label("1")
    if kind == BinaryOpKind.SHIFT_LEFT:
        builder.instruction("shl", _PRIMARY_REGISTER, _SECONDARY_BYTE_REGISTER)
        _mask_u8_result_if_needed(builder, operand_type_name)
        return
    if operand_type_name in _UNSIGNED_TYPE_NAMES:
        builder.instruction("shr", _PRIMARY_REGISTER, _SECONDARY_BYTE_REGISTER)
        return
    builder.instruction("sar", _PRIMARY_REGISTER, _SECONDARY_BYTE_REGISTER)


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


def _emit_identity_comparison(builder: X86AsmBuilder, kind: BinaryOpKind) -> None:
    if kind not in {BinaryOpKind.EQUAL, BinaryOpKind.NOT_EQUAL}:
        raise BackendTargetLoweringError(
            f"x86_64_sysv identity comparison operator '{kind.value}' is not supported"
        )
    builder.instruction("cmp", _PRIMARY_REGISTER, _SECONDARY_REGISTER)
    builder.instruction("sete" if kind == BinaryOpKind.EQUAL else "setne", _PRIMARY_BYTE_REGISTER)
    builder.instruction("movzx", _PRIMARY_REGISTER, _PRIMARY_BYTE_REGISTER)


def _emit_scalar_cast(builder: X86AsmBuilder, instruction: BackendCastInst, *, source_type_name: str) -> None:
    target_type_name = semantic_type_canonical_name(instruction.target_type_ref)
    if instruction.cast_kind is CastSemanticsKind.TO_INTEGER and source_type_name == TYPE_NAME_U64 and target_type_name == TYPE_NAME_I64:
        return
    raise BackendTargetLoweringError(
        f"x86_64_sysv cast '{instruction.cast_kind.value}' from '{source_type_name}' to '{target_type_name}' is not supported in PR4"
    )


def emit_load_operand(
    builder: X86AsmBuilder,
    operand: BackendOperand,
    *,
    target_register: str,
    target_byte_register: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_symbols=None,
) -> None:
    if isinstance(operand, BackendRegOperand):
        physical_register = _physical_register_for_reg(frame_layout, operand.reg_id)
        if physical_register is not None:
            if physical_register.name != target_register:
                builder.instruction("mov", target_register, physical_register.name)
            if register_type_name_by_reg_id[operand.reg_id] == TYPE_NAME_BOOL:
                _normalize_bool_register(builder, target_register, target_byte_register)
            return

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
    if isinstance(operand, BackendCallableOperand):
        if program_symbols is None:
            raise BackendTargetLoweringError("x86_64_sysv callable operands require backend program symbols")
        builder.instruction("lea", target_register, f"[rip + {program_symbols.callable(operand.callable_id).direct_call_symbol}]")
        return

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
    physical_register = _physical_register_for_reg(frame_layout, dest_reg_id)
    if physical_register is not None:
        if physical_register.name != source_register:
            builder.instruction("mov", physical_register.name, source_register)
        return
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
    if isinstance(operand, BackendCallableOperand):
        return semantic_type_canonical_name(operand.type_ref)
    raise BackendTargetLoweringError(
        f"x86_64_sysv cannot infer operand type for '{type(operand).__name__}' in PR3"
    )


def _double_value_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _normalize_bool_register(builder: X86AsmBuilder, register_name: str, byte_register_name: str) -> None:
    builder.instruction("cmp", register_name, "0")
    builder.instruction("setne", byte_register_name)
    builder.instruction("movzx", register_name, byte_register_name)


def _mask_u8_result_if_needed(
    builder: X86AsmBuilder,
    operand_type_name: str,
    *,
    target_register: str = _PRIMARY_REGISTER,
) -> None:
    if operand_type_name == TYPE_NAME_U8:
        builder.instruction("and", target_register, "255")


def _physical_register_name_for_dest(frame_layout: X86_64SysVFrameLayout, dest_reg_id) -> str | None:
    physical_register = _physical_register_for_reg(frame_layout, dest_reg_id)
    return None if physical_register is None else physical_register.name


def _operand_physical_register_name(frame_layout: X86_64SysVFrameLayout, operand: BackendOperand) -> str | None:
    if not isinstance(operand, BackendRegOperand):
        return None
    physical_register = _physical_register_for_reg(frame_layout, operand.reg_id)
    return None if physical_register is None else physical_register.name


def _stack_operand_for_reg(frame_layout: X86_64SysVFrameLayout, reg_id) -> str:
    slot = frame_layout.for_reg(reg_id)
    if slot is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv frame layout is missing a home for register 'r{reg_id.ordinal}'"
        )
    return format_stack_slot_operand("rbp", slot.byte_offset)


def _emit_load_scalar_operand_into_register(
    builder: X86AsmBuilder,
    operand: BackendOperand,
    *,
    target_register: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
) -> None:
    source_register = _operand_physical_register_name(frame_layout, operand)
    if source_register == target_register:
        if isinstance(operand, BackendRegOperand) and register_type_name_by_reg_id[operand.reg_id] == TYPE_NAME_BOOL:
            _normalize_bool_register(builder, target_register, _byte_register_name_for_register(target_register))
        return

    emit_load_operand(
        builder,
        operand,
        target_register=target_register,
        target_byte_register=_byte_register_name_for_register(target_register),
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
    )


def _scalar_asm_operand_for_binary_rhs(
    operand: BackendOperand,
    *,
    frame_layout: X86_64SysVFrameLayout,
    allow_immediate: bool,
) -> str | None:
    if isinstance(operand, BackendRegOperand):
        physical_register_name = _operand_physical_register_name(frame_layout, operand)
        if physical_register_name is not None:
            return physical_register_name
        return _stack_operand_for_reg(frame_layout, operand.reg_id)
    if allow_immediate and isinstance(operand, BackendConstOperand) and _constant_fits_signed_32_bit_immediate(operand):
        return _constant_integer_operand(operand)
    return None


def _constant_fits_signed_32_bit_immediate(operand: BackendConstOperand) -> bool:
    if not isinstance(operand.constant, BackendIntConst):
        return False
    return -(2**31) <= operand.constant.value <= 2**31 - 1


def _constant_integer_operand(operand: BackendConstOperand) -> str:
    if isinstance(operand.constant, BackendIntConst):
        return str(operand.constant.value)
    raise BackendTargetLoweringError(
        f"x86_64_sysv expected an integer constant operand, got '{type(operand.constant).__name__}'"
    )


def _try_emit_direct_scalar_copy(
    builder: X86AsmBuilder,
    source: BackendOperand,
    dest_reg_id,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_symbols=None,
) -> bool:
    dest_physical_register = _physical_register_for_reg(frame_layout, dest_reg_id)
    dest_stack_slot = frame_layout.for_reg(dest_reg_id)
    if dest_stack_slot is None:
        raise BackendTargetLoweringError(
            f"x86_64_sysv frame layout is missing a home for destination register 'r{dest_reg_id.ordinal}'"
        )

    if isinstance(source, BackendRegOperand):
        source_physical_register = _physical_register_for_reg(frame_layout, source.reg_id)
        if dest_physical_register is not None and source_physical_register is not None:
            if dest_physical_register.name != source_physical_register.name:
                builder.instruction("mov", dest_physical_register.name, source_physical_register.name)
            _normalize_direct_copy_bool_if_needed(
                builder,
                dest_reg_id,
                dest_physical_register.name,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            return True
        if dest_physical_register is not None:
            source_stack_slot = frame_layout.for_reg(source.reg_id)
            if source_stack_slot is None:
                raise BackendTargetLoweringError(
                    f"x86_64_sysv frame layout is missing a home for source register 'r{source.reg_id.ordinal}'"
                )
            builder.instruction(
                "mov",
                dest_physical_register.name,
                format_stack_slot_operand("rbp", source_stack_slot.byte_offset),
            )
            _normalize_direct_copy_bool_if_needed(
                builder,
                dest_reg_id,
                dest_physical_register.name,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            return True
        if source_physical_register is not None:
            builder.instruction(
                "mov",
                format_stack_slot_operand("rbp", dest_stack_slot.byte_offset),
                source_physical_register.name,
            )
            return True
        return False

    if isinstance(source, BackendConstOperand) and dest_physical_register is not None:
        _emit_load_constant(builder, source.constant, target_register=dest_physical_register.name)
        _normalize_direct_copy_bool_if_needed(
            builder,
            dest_reg_id,
            dest_physical_register.name,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
        )
        return True

    if isinstance(source, BackendCallableOperand) and dest_physical_register is not None:
        if program_symbols is None:
            raise BackendTargetLoweringError("x86_64_sysv callable operands require backend program symbols")
        builder.instruction(
            "lea",
            dest_physical_register.name,
            f"[rip + {program_symbols.callable(source.callable_id).direct_call_symbol}]",
        )
        return True

    return False


def _normalize_direct_copy_bool_if_needed(
    builder: X86AsmBuilder,
    dest_reg_id,
    dest_register_name: str,
    *,
    register_type_name_by_reg_id: dict,
) -> None:
    if register_type_name_by_reg_id[dest_reg_id] != TYPE_NAME_BOOL:
        return
    _normalize_bool_register(builder, dest_register_name, _byte_register_name_for_register(dest_register_name))


def _byte_register_name_for_register(register_name: str) -> str:
    byte_register_by_register = {
        "rax": "al",
        "rbx": "bl",
        "rcx": "cl",
        "rdx": "dl",
        "rsi": "sil",
        "rdi": "dil",
        "r8": "r8b",
        "r9": "r9b",
        "r10": "r10b",
        "r11": "r11b",
        "r12": "r12b",
        "r13": "r13b",
        "r14": "r14b",
        "r15": "r15b",
    }
    try:
        return byte_register_by_register[register_name]
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"x86_64_sysv instruction selection does not know the byte register for '{register_name}'"
        ) from exc


def _physical_register_for_reg(frame_layout: X86_64SysVFrameLayout, reg_id) -> object | None:
    allocation = frame_layout.allocation
    if allocation is None:
        return None
    location = allocation.location_by_reg.get(reg_id)
    if location is None or location.physical_register is None:
        return None
    return location.physical_register


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
