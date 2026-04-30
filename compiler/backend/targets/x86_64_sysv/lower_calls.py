"""Call lowering for the x86-64 SysV backend target."""

from __future__ import annotations

from compiler.backend.ir import (
    BackendCallInst,
    BackendDataOperand,
    BackendDirectCallTarget,
    BackendIndirectCallTarget,
    BackendInterfaceCallTarget,
    BackendRuntimeCallTarget,
    BackendVirtualCallTarget,
)
from compiler.backend.program import BackendProgramContext
from compiler.backend.program.symbols import BackendProgramSymbolTable
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
from compiler.backend.targets.x86_64_sysv.object_runtime import (
    class_vtable_entry_operand,
    class_vtable_operand,
    interface_method_entry_operand,
    interface_table_entry_operand,
    interface_tables_operand,
    object_type_operand,
)
from compiler.semantic.symbols import ClassId


_CALL_TEMP_REGISTER = "rax"
_CALL_TEMP_BYTE_REGISTER = "al"
_CALL_TEMP_FLOAT_REGISTER = "xmm15"
_CALL_TARGET_REGISTER = "r11"
_CALL_TARGET_BYTE_REGISTER = "r11b"
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


def emit_call_instruction(
    builder: X86AsmBuilder,
    instruction: BackendCallInst,
    *,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    callable_decl_by_id: dict,
    program_symbols: BackendProgramSymbolTable,
    program_context: BackendProgramContext,
    interface_method_slot_by_id: dict,
    callable_label: str,
    emit_safepoint_preamble=None,
    emit_safepoint_postamble=None,
    abi: X86_64SysVAbi = X86_64_SYSV_ABI,
) -> None:
    if not isinstance(
        instruction.target,
        (
            BackendDirectCallTarget,
            BackendRuntimeCallTarget,
            BackendIndirectCallTarget,
            BackendVirtualCallTarget,
            BackendInterfaceCallTarget,
        ),
    ):
        raise BackendTargetLoweringError(
            f"x86_64_sysv call lowering does not support target '{type(instruction.target).__name__}'"
        )

    callee_decl = None
    if isinstance(instruction.target, BackendDirectCallTarget):
        callee_decl = callable_decl_by_id.get(instruction.target.callable_id)
        if callee_decl is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv direct call lowering could not resolve callable '{instruction.target.callable_id}'"
            )

    includes_receiver = _call_includes_receiver(instruction)

    arg_locations = abi.plan_argument_locations(
        instruction.signature.param_types,
        includes_receiver=includes_receiver,
    )
    if len(arg_locations) != len(instruction.args):
        raise BackendTargetLoweringError(
            "x86_64_sysv direct call lowering requires argument count to match the lowered call signature"
        )

    stack_arg_slot_count = abi.outgoing_stack_arg_slot_count(
        instruction.signature.param_types,
        includes_receiver=includes_receiver,
    )
    if stack_arg_slot_count > len(frame_layout.outgoing_stack_arg_offsets):
        raise BackendTargetLoweringError(
            "x86_64_sysv frame layout does not reserve enough outgoing stack-argument slots for this call"
        )

    if emit_safepoint_preamble is not None and (instruction.effects.may_gc or instruction.effects.needs_safepoint_hooks):
        emit_safepoint_preamble(instruction)

    call_stack_reservation_bytes = abi.call_stack_reservation_bytes(stack_arg_slot_count)
    if call_stack_reservation_bytes > 0:
        builder.instruction("sub", "rsp", str(call_stack_reservation_bytes))

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
            _emit_load_call_operand(
                builder,
                operand,
                target_register=arg_location.register_name,
                target_byte_register=_byte_register_name(arg_location.register_name),
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
                _emit_load_call_operand(
                    builder,
                    operand,
                    target_register=_CALL_TEMP_REGISTER,
                    target_byte_register=_CALL_TEMP_BYTE_REGISTER,
                    frame_layout=frame_layout,
                    register_type_name_by_reg_id=register_type_name_by_reg_id,
                    program_symbols=program_symbols,
                )
                builder.instruction("mov", stack_operand, _CALL_TEMP_REGISTER)
            continue

        raise BackendTargetLoweringError(
            f"x86_64_sysv direct call lowering does not support argument location kind '{arg_location.kind}'"
        )

    if includes_receiver and _receiver_null_check_required(instruction, callee_decl):
        _emit_receiver_null_check(builder, callable_label=callable_label, instruction=instruction)

    _emit_call_target_invocation(
        builder,
        instruction,
        callee_decl=callee_decl,
        program_symbols=program_symbols,
        program_context=program_context,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
        frame_layout=frame_layout,
        interface_method_slot_by_id=interface_method_slot_by_id,
        callable_label=callable_label,
        includes_receiver=includes_receiver,
    )

    if call_stack_reservation_bytes > 0:
        builder.instruction("add", "rsp", str(call_stack_reservation_bytes))

    if emit_safepoint_postamble is not None and instruction.effects.may_gc:
        emit_safepoint_postamble(instruction)

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


def _call_includes_receiver(instruction: BackendCallInst) -> bool:
    if isinstance(instruction.target, (BackendVirtualCallTarget, BackendInterfaceCallTarget)):
        return True
    if isinstance(instruction.target, (BackendDirectCallTarget, BackendIndirectCallTarget)):
        return len(instruction.args) == len(instruction.signature.param_types) + 1
    return False


def _receiver_null_check_required(instruction: BackendCallInst, callee_decl) -> bool:
    if isinstance(instruction.target, BackendDirectCallTarget):
        return callee_decl is not None and callee_decl.kind == "method"
    return isinstance(
        instruction.target,
        (
            BackendIndirectCallTarget,
            BackendVirtualCallTarget,
            BackendInterfaceCallTarget,
        ),
    )


def _emit_receiver_null_check(builder: X86AsmBuilder, *, callable_label: str, instruction: BackendCallInst) -> None:
    non_null_label = f".L{callable_label}_i{instruction.inst_id.ordinal}_recv_nonnull"
    builder.instruction("test", "rdi", "rdi")
    builder.instruction("jne", non_null_label)
    builder.instruction("call", "rt_panic_null_deref")
    builder.label(non_null_label)


def _emit_call_target_invocation(
    builder: X86AsmBuilder,
    instruction: BackendCallInst,
    *,
    callee_decl,
    program_symbols: BackendProgramSymbolTable,
    program_context: BackendProgramContext,
    register_type_name_by_reg_id: dict,
    frame_layout: X86_64SysVFrameLayout,
    interface_method_slot_by_id: dict,
    callable_label: str,
    includes_receiver: bool,
) -> None:
    if isinstance(instruction.target, (BackendDirectCallTarget, BackendRuntimeCallTarget)):
        builder.instruction("call", _call_target_symbol(instruction, program_symbols, callee_decl, includes_receiver=includes_receiver))
        return

    if isinstance(instruction.target, BackendIndirectCallTarget):
        _emit_load_call_operand(
            builder,
            instruction.target.callee,
            target_register=_CALL_TARGET_REGISTER,
            target_byte_register=_CALL_TARGET_BYTE_REGISTER,
            frame_layout=frame_layout,
            register_type_name_by_reg_id=register_type_name_by_reg_id,
            program_symbols=program_symbols,
        )
        builder.instruction("call", _CALL_TARGET_REGISTER)
        return

    if isinstance(instruction.target, BackendVirtualCallTarget):
        _emit_virtual_call_target_lookup(builder, instruction=instruction, program_context=program_context)
        builder.instruction("call", _CALL_TARGET_REGISTER)
        return

    if isinstance(instruction.target, BackendInterfaceCallTarget):
        _emit_interface_call_target_lookup(
            builder,
            instruction=instruction,
            program_context=program_context,
            interface_method_slot_by_id=interface_method_slot_by_id,
        )
        builder.instruction("call", _CALL_TARGET_REGISTER)
        return

    raise BackendTargetLoweringError(
        f"x86_64_sysv call lowering does not support target '{type(instruction.target).__name__}'"
    )


def _emit_virtual_call_target_lookup(
    builder: X86AsmBuilder,
    *,
    instruction: BackendCallInst,
    program_context: BackendProgramContext,
) -> None:
    assert isinstance(instruction.target, BackendVirtualCallTarget)
    selected_method_class_id = ClassId(
        module_path=instruction.target.selected_method_id.module_path,
        name=instruction.target.selected_method_id.class_name,
    )
    slot_index = program_context.class_hierarchy.resolve_virtual_slot_index(
        selected_method_class_id,
        instruction.target.slot_owner_class_id,
        instruction.target.method_name,
    )
    builder.instruction("mov", "rcx", object_type_operand("rdi"))
    builder.instruction("mov", "rcx", class_vtable_operand("rcx"))
    builder.instruction("mov", _CALL_TARGET_REGISTER, class_vtable_entry_operand("rcx", slot_index))


def _emit_interface_call_target_lookup(
    builder: X86AsmBuilder,
    *,
    instruction: BackendCallInst,
    program_context: BackendProgramContext,
    interface_method_slot_by_id: dict,
) -> None:
    assert isinstance(instruction.target, BackendInterfaceCallTarget)
    slot_index = _interface_slot_index(program_context, instruction.target.interface_id)
    try:
        method_slot = interface_method_slot_by_id[instruction.target.method_id]
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"x86_64_sysv backend program context is missing interface method slot metadata for '{instruction.target.method_id}'"
        ) from exc
    builder.instruction("mov", "rcx", object_type_operand("rdi"))
    builder.instruction("mov", "rcx", interface_tables_operand("rcx"))
    builder.instruction("mov", "rcx", interface_table_entry_operand("rcx", slot_index))
    builder.instruction("mov", _CALL_TARGET_REGISTER, interface_method_entry_operand("rcx", method_slot))


def _interface_slot_index(program_context: BackendProgramContext, interface_id) -> int:
    for interface_record in program_context.metadata.interfaces:
        if interface_record.interface_id == interface_id:
            return interface_record.slot_index
    raise BackendTargetLoweringError(
        f"x86_64_sysv backend program context is missing interface metadata for '{interface_id}'"
    )


def _byte_register_name(register_name: str) -> str:
    try:
        return _BYTE_REGISTER_BY_REGISTER[register_name]
    except KeyError as exc:
        raise BackendTargetLoweringError(
            f"x86_64_sysv direct call lowering does not know the byte register for '{register_name}'"
        ) from exc


def _emit_load_call_operand(
    builder: X86AsmBuilder,
    operand,
    *,
    target_register: str,
    target_byte_register: str,
    frame_layout: X86_64SysVFrameLayout,
    register_type_name_by_reg_id: dict,
    program_symbols: BackendProgramSymbolTable,
) -> None:
    if isinstance(operand, BackendDataOperand):
        builder.instruction("lea", target_register, f"[rip + {program_symbols.data_blob_symbols(operand.data_id).symbol}]")
        return
    emit_load_operand(
        builder,
        operand,
        target_register=target_register,
        target_byte_register=target_byte_register,
        frame_layout=frame_layout,
        register_type_name_by_reg_id=register_type_name_by_reg_id,
        program_symbols=program_symbols,
    )


def _call_target_symbol(
    instruction: BackendCallInst,
    program_symbols: BackendProgramSymbolTable,
    callee_decl,
    *,
    includes_receiver: bool,
) -> str:
    if isinstance(instruction.target, BackendRuntimeCallTarget):
        return instruction.target.name
    assert callee_decl is not None
    callable_symbols = program_symbols.callable(callee_decl.callable_id)
    if callee_decl.kind == "constructor" and includes_receiver:
        if callable_symbols.constructor_init_symbol is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv constructor '{callee_decl.callable_id}' is missing an init symbol"
            )
        return callable_symbols.constructor_init_symbol
    return callable_symbols.direct_call_symbol


def emit_direct_call_instruction(*args, **kwargs):
    return emit_call_instruction(*args, **kwargs)


__all__ = ["emit_call_instruction", "emit_direct_call_instruction"]
