"""Reduced-scope direct-call lowering for the x86-64 SysV backend target."""

from __future__ import annotations

from collections.abc import Callable

from compiler.backend.ir import BackendCallInst, BackendDirectCallTarget
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI, X86_64SysVAbi
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout
from compiler.backend.targets.x86_64_sysv.instruction_selection import (
    emit_load_float_operand,
    emit_load_operand,
    emit_store_float_result,
    emit_store_result,
)


_CALL_TEMP_REGISTER = "rax"
_CALL_TEMP_BYTE_REGISTER = "al"
_CALL_TEMP_FLOAT_REGISTER = "xmm15"
_BYTE_REGISTER_BY_REGISTER = {
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
}


def emit_direct_call_instruction(
    builder: X86AsmBuilder,
    instruction: BackendCallInst,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    resolve_direct_call_target_symbol: Callable[[object], str],
    abi: X86_64SysVAbi = X86_64_SYSV_ABI,
) -> None:
    if not isinstance(instruction.target, BackendDirectCallTarget):
        raise BackendTargetLoweringError(
            f"x86_64_sysv reduced call lowering does not support target '{type(instruction.target).__name__}'"
        )

    arg_locations = abi.plan_argument_locations(instruction.signature.param_types)
    if len(arg_locations) != len(instruction.args):
        raise BackendTargetLoweringError(
            "x86_64_sysv direct call lowering requires argument count to match the lowered call signature"
        )

    stack_arg_slot_count = abi.outgoing_stack_arg_slot_count(instruction.signature.param_types)
    if stack_arg_slot_count > len(frame_layout.outgoing_stack_arg_offsets):
        raise BackendTargetLoweringError(
            "x86_64_sysv frame layout does not reserve enough outgoing stack-argument slots for this call"
        )

    call_stack_reservation_bytes = abi.call_stack_reservation_bytes(stack_arg_slot_count)
    if call_stack_reservation_bytes > 0:
        builder.instruction("sub", "rsp", str(call_stack_reservation_bytes))

    for operand, arg_location, param_type in zip(
        instruction.args,
        arg_locations,
        instruction.signature.param_types,
        strict=True,
    ):
        if arg_location.kind == "int_reg":
            assert arg_location.register_name is not None
            emit_load_operand(
                builder,
                operand,
                target_register=arg_location.register_name,
                target_byte_register=_byte_register_name(arg_location.register_name),
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            continue

        if arg_location.kind == "float_reg":
            assert arg_location.register_name is not None
            emit_load_float_operand(
                builder,
                operand,
                target_float_register=arg_location.register_name,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
            )
            continue

        if arg_location.kind == "stack":
            assert arg_location.stack_slot_index is not None
            stack_operand = format_stack_slot_operand("rsp", arg_location.stack_slot_index * abi.stack_slot_size_bytes)
            if abi.is_float_type(param_type):
                emit_load_float_operand(
                    builder,
                    operand,
                    target_float_register=_CALL_TEMP_FLOAT_REGISTER,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                )
                builder.instruction("movq", stack_operand, _CALL_TEMP_FLOAT_REGISTER)
            else:
                emit_load_operand(
                    builder,
                    operand,
                    target_register=_CALL_TEMP_REGISTER,
                    target_byte_register=_CALL_TEMP_BYTE_REGISTER,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                )
                builder.instruction("mov", stack_operand, _CALL_TEMP_REGISTER)
            continue

        raise BackendTargetLoweringError(
            f"x86_64_sysv direct call lowering does not support argument location kind '{arg_location.kind}'"
        )

    builder.instruction("call", resolve_direct_call_target_symbol(instruction.target.callable_id))

    if call_stack_reservation_bytes > 0:
        builder.instruction("add", "rsp", str(call_stack_reservation_bytes))

    if instruction.signature.return_type is None:
        if instruction.dest is not None:
            raise BackendTargetLoweringError(
                "x86_64_sysv direct call lowering cannot store a unit-return call into a destination register"
            )
        return

    return_register = abi.return_register_for_type(instruction.signature.return_type)
    if return_register is None:
        raise BackendTargetLoweringError("x86_64_sysv direct call lowering expected a concrete return register")
    if instruction.dest is not None:
        if abi.is_float_type(instruction.signature.return_type):
            emit_store_float_result(builder, instruction.dest, frame_layout=frame_layout, source_float_register=return_register)
        else:
            emit_store_result(builder, instruction.dest, frame_layout=frame_layout, source_register=return_register)


def _byte_register_name(register_name: str) -> str:
    try:
        return _BYTE_REGISTER_BY_REGISTER[register_name]
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"x86_64_sysv direct call lowering does not know the byte register for '{register_name}'"
        ) from exc


__all__ = ["emit_direct_call_instruction"]
