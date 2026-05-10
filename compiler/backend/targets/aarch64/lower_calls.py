"""Call lowering for the AArch64 backend target."""

from __future__ import annotations

from compiler.backend.ir import (
    BackendCallInst,
    BackendDirectCallTarget,
    BackendIndirectCallTarget,
    BackendRuntimeCallTarget,
)
from compiler.backend.program.symbols import BackendProgramSymbolTable
from compiler.backend.targets import BackendTargetLoweringError
from compiler.backend.targets.aarch64.abi import AARCH64_ABI, AArch64Abi
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, format_memory_operand
from compiler.backend.targets.aarch64.frame import AArch64FrameLayout
from compiler.backend.targets.aarch64.instruction_selection import (
    emit_load_float_operand,
    emit_load_operand,
    emit_store_float_result,
    emit_store_result,
)


_CALL_TEMP_REGISTER = "x9"
_CALL_TEMP_FLOAT_REGISTER = "d16"
_CALL_TARGET_REGISTER = "x16"


def emit_call_instruction(
    builder: AArch64AsmBuilder,
    instruction: BackendCallInst,
    *,
    frame_layout: AArch64FrameLayout,
    register_type_name_by_reg_id: dict,
    callable_decl_by_id: dict,
    program_symbols: BackendProgramSymbolTable,
    callable_label: str,
    emit_safepoint_preamble=None,
    emit_safepoint_postamble=None,
    abi: AArch64Abi = AARCH64_ABI,
) -> None:
    if not isinstance(
        instruction.target,
        (BackendDirectCallTarget, BackendRuntimeCallTarget, BackendIndirectCallTarget),
    ):
        raise BackendTargetLoweringError(
            f"aarch64 call lowering does not support target '{type(instruction.target).__name__}' in slice 4"
        )

    callee_decl = None
    if isinstance(instruction.target, BackendDirectCallTarget):
        callee_decl = callable_decl_by_id.get(instruction.target.callable_id)
        if callee_decl is None:
            raise BackendTargetLoweringError(
                f"aarch64 direct call lowering could not resolve callable '{instruction.target.callable_id}'"
            )
        if callee_decl.kind == "constructor":
            raise BackendTargetLoweringError(
                "aarch64 constructor entry wrappers land in the later object slice"
            )

    includes_receiver = _call_includes_receiver(instruction)
    arg_locations = abi.plan_argument_locations(
        instruction.signature.param_types,
        includes_receiver=includes_receiver,
    )
    if len(arg_locations) != len(instruction.args):
        raise BackendTargetLoweringError(
            "aarch64 call lowering requires argument count to match the lowered call signature"
        )

    stack_arg_slot_count = abi.outgoing_stack_arg_slot_count(
        instruction.signature.param_types,
        includes_receiver=includes_receiver,
    )
    if stack_arg_slot_count > len(frame_layout.outgoing_stack_arg_offsets):
        raise BackendTargetLoweringError(
            "aarch64 frame layout does not reserve enough outgoing stack-argument slots for this call"
        )

    if emit_safepoint_preamble is not None and (instruction.effects.may_gc or instruction.effects.needs_safepoint_hooks):
        emit_safepoint_preamble(instruction)

    call_stack_reservation_bytes = abi.call_stack_reservation_bytes(stack_arg_slot_count)
    if call_stack_reservation_bytes > 0:
        builder.instruction("sub", "sp", "sp", f"#{call_stack_reservation_bytes}")

    argument_param_types = instruction.signature.param_types
    if includes_receiver:
        argument_param_types = (None, *argument_param_types)

    for operand, arg_location, param_type in zip(
        instruction.args,
        arg_locations,
        argument_param_types,
        strict=True,
    ):
        if arg_location.kind == "int_reg":
            assert arg_location.register_name is not None
            emit_load_operand(
                builder,
                operand,
                target_register=arg_location.register_name,
                frame_layout=frame_layout,
                register_type_name_by_reg_id=register_type_name_by_reg_id,
                program_symbols=program_symbols,
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
            stack_operand = format_memory_operand("sp", arg_location.stack_slot_index * abi.stack_slot_size_bytes)
            if abi.is_float_type(param_type):
                emit_load_float_operand(
                    builder,
                    operand,
                    target_float_register=_CALL_TEMP_FLOAT_REGISTER,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                )
                builder.instruction("str", _CALL_TEMP_FLOAT_REGISTER, stack_operand)
            else:
                emit_load_operand(
                    builder,
                    operand,
                    target_register=_CALL_TEMP_REGISTER,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                    program_symbols=program_symbols,
                )
                builder.instruction("str", _CALL_TEMP_REGISTER, stack_operand)
            continue

        raise BackendTargetLoweringError(
            f"aarch64 call lowering does not support argument location kind '{arg_location.kind}'"
        )

    if includes_receiver and _receiver_null_check_required(instruction, callee_decl):
        _emit_receiver_null_check(builder, callable_label=callable_label, instruction=instruction)

    if isinstance(instruction.target, (BackendDirectCallTarget, BackendRuntimeCallTarget)):
        builder.instruction("bl", _call_target_symbol(instruction, program_symbols, callee_decl))
    else:
        emit_load_operand(
            builder,
            instruction.target.callee,
            target_register=_CALL_TARGET_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            program_symbols=program_symbols,
        )
        builder.instruction("blr", _CALL_TARGET_REGISTER)

    if call_stack_reservation_bytes > 0:
        builder.instruction("add", "sp", "sp", f"#{call_stack_reservation_bytes}")

    if emit_safepoint_postamble is not None and instruction.effects.may_gc:
        emit_safepoint_postamble(instruction)

    if instruction.signature.return_type is None:
        if instruction.dest is not None:
            raise BackendTargetLoweringError(
                "aarch64 call lowering cannot store a unit-return call into a destination register"
            )
        return

    return_register = abi.return_register_for_type(instruction.signature.return_type)
    if return_register is None:
        raise BackendTargetLoweringError("aarch64 call lowering expected a concrete return register")
    if instruction.dest is not None:
        if abi.is_float_type(instruction.signature.return_type):
            emit_store_float_result(
                builder,
                instruction.dest,
                frame_layout=frame_layout,
                source_float_register=return_register,
            )
        else:
            emit_store_result(
                builder,
                instruction.dest,
                frame_layout=frame_layout,
                source_register=return_register,
            )


def _call_includes_receiver(instruction: BackendCallInst) -> bool:
    if isinstance(instruction.target, (BackendDirectCallTarget, BackendIndirectCallTarget)):
        return len(instruction.args) == len(instruction.signature.param_types) + 1
    return False


def _receiver_null_check_required(instruction: BackendCallInst, callee_decl) -> bool:
    if isinstance(instruction.target, BackendDirectCallTarget):
        return callee_decl is not None and callee_decl.kind == "method"
    return isinstance(instruction.target, BackendIndirectCallTarget)


def _emit_receiver_null_check(builder: AArch64AsmBuilder, *, callable_label: str, instruction: BackendCallInst) -> None:
    non_null_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_recv_nonnull"
    builder.instruction("cbnz", "x0", non_null_label)
    builder.instruction("bl", "rt_panic_null_deref")
    builder.label(non_null_label)


def _call_target_symbol(instruction: BackendCallInst, program_symbols: BackendProgramSymbolTable, callee_decl) -> str:
    if isinstance(instruction.target, BackendRuntimeCallTarget):
        return instruction.target.name
    assert isinstance(instruction.target, BackendDirectCallTarget)
    if callee_decl is not None and callee_decl.is_extern:
        return instruction.target.callable_id.name
    return program_symbols.callable(instruction.target.callable_id).direct_call_symbol


__all__ = ["emit_call_instruction"]