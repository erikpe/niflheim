from __future__ import annotations

from compiler.backend.ir import (
    BackendAllocObjectInst,
    BackendArrayAllocInst,
    BackendArrayLengthInst,
    BackendArrayLoadInst,
    BackendArraySliceInst,
    BackendArraySliceStoreInst,
    BackendArrayStoreInst,
    BackendBlock,
    BackendBoundsCheckInst,
    BackendCallInst,
    BackendCastInst,
    BackendConstInst,
    BackendDirectCallTarget,
    BackendDoubleConst,
    BackendFieldLoadInst,
    BackendFieldStoreInst,
    BackendIndirectCallTarget,
    BackendInterfaceCallTarget,
    BackendNullCheckInst,
    BackendTrapTerminator,
    BackendTypeTestInst,
    BackendVirtualCallTarget,
)
from compiler.backend.targets import (
    BackendEmitResult,
    BackendTarget,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
)
from compiler.backend.targets.x86_64_sysv.abi import X86_64_SYSV_ABI
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import plan_callable_frame_layout
from compiler.backend.targets.x86_64_sysv.instruction_selection import emit_straight_line_callable_body
from compiler.codegen.symbols import epilogue_label, mangle_function_symbol
from compiler.semantic.symbols import ConstructorId, FunctionId, MethodId


TARGET_NAME = "x86_64_sysv"


class X86_64SysVLegalityError(BackendTargetLoweringError):
    """Raised when backend IR falls outside the reduced phase-4 x86-64 SysV slice."""


class X86_64SysVTarget:
    name = TARGET_NAME

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
        return emit_x86_64_sysv_asm(target_input, options=options)


def emit_x86_64_sysv_asm(target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
    check_x86_64_sysv_legality(target_input)

    builder = X86AsmBuilder(emit_debug_comments=options.emit_debug_comments)
    builder.blank()
    builder.directive(".text")

    for callable_decl in target_input.program.callables:
        if callable_decl.is_extern:
            continue
        builder.blank()
        frame_layout = plan_callable_frame_layout(target_input, callable_decl)
        _emit_callable_body(
            builder,
            callable_decl,
            frame_layout=frame_layout,
            entry_callable_id=target_input.program.entry_callable_id,
            emit_debug_comments=options.emit_debug_comments,
        )

    builder.blank()
    builder.directive('.section .note.GNU-stack,"",@progbits')
    builder.blank()
    return BackendEmitResult(assembly_text=builder.build(), diagnostics=())


def check_x86_64_sysv_legality(target_input: BackendTargetInput) -> None:
    for callable_decl in target_input.program.callables:
        _check_callable_shape(callable_decl)
        _check_callable_signature(callable_decl)
        _check_callable_register_types(callable_decl)
        _check_callable_analysis(target_input, callable_decl)
        for block in callable_decl.blocks:
            for instruction in block.instructions:
                _check_instruction_legality(callable_decl, block, instruction)


def _check_callable_shape(callable_decl) -> None:
    if callable_decl.kind != "function":
        _callable_error(callable_decl, "reduced phase-4 x86_64_sysv only supports plain functions")
    if callable_decl.receiver_reg is not None:
        _callable_error(callable_decl, "reduced phase-4 x86_64_sysv does not support receiver-aware callables")


def _check_callable_signature(callable_decl) -> None:
    for param_type in callable_decl.signature.param_types:
        if not X86_64_SYSV_ABI.supports_scalar_type(param_type):
            _callable_error(
                callable_decl,
                f"unsupported reduced-scope parameter type '{param_type.display_name}'",
            )
    if not X86_64_SYSV_ABI.supports_scalar_type(callable_decl.signature.return_type):
        assert callable_decl.signature.return_type is not None
        _callable_error(
            callable_decl,
            f"unsupported reduced-scope return type '{callable_decl.signature.return_type.display_name}'",
        )


def _check_callable_register_types(callable_decl) -> None:
    for register in callable_decl.registers:
        if not X86_64_SYSV_ABI.supports_scalar_type(register.type_ref):
            _callable_error(
                callable_decl,
                f"register 'r{register.reg_id.ordinal}' uses unsupported reduced-scope type '{register.type_ref.display_name}'",
            )


def _check_callable_analysis(target_input: BackendTargetInput, callable_decl) -> None:
    callable_analysis = target_input.analysis_for_callable(callable_decl.callable_id)
    if callable_analysis.root_slots.root_slot_by_reg:
        _callable_error(
            callable_decl,
            "reduced phase-4 x86_64_sysv does not yet support GC root-slot setup",
        )


def _check_instruction_legality(callable_decl, block: BackendBlock, instruction: object) -> None:
    if isinstance(instruction, BackendConstInst) and isinstance(instruction.constant, BackendDoubleConst):
        _instruction_error(callable_decl, block, instruction, "double constants are not supported in reduced phase-4 x86_64_sysv")
        return

    unsupported_types = (
        BackendCastInst,
        BackendTypeTestInst,
        BackendAllocObjectInst,
        BackendFieldLoadInst,
        BackendFieldStoreInst,
        BackendArrayAllocInst,
        BackendArrayLengthInst,
        BackendArrayLoadInst,
        BackendArrayStoreInst,
        BackendArraySliceInst,
        BackendArraySliceStoreInst,
        BackendNullCheckInst,
        BackendBoundsCheckInst,
    )
    if isinstance(instruction, unsupported_types):
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"instruction '{type(instruction).__name__}' is not supported in reduced phase-4 x86_64_sysv",
        )
        return

    if isinstance(instruction, BackendCallInst):
        if not isinstance(instruction.target, BackendDirectCallTarget):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call target '{type(instruction.target).__name__}' is not supported in reduced phase-4 x86_64_sysv",
            )
        for param_type in instruction.signature.param_types:
            if not X86_64_SYSV_ABI.supports_scalar_type(param_type):
                _instruction_error(
                    callable_decl,
                    block,
                    instruction,
                    f"call parameter type '{param_type.display_name}' is not supported in reduced phase-4 x86_64_sysv",
                )
        if not X86_64_SYSV_ABI.supports_scalar_type(instruction.signature.return_type):
            assert instruction.signature.return_type is not None
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call return type '{instruction.signature.return_type.display_name}' is not supported in reduced phase-4 x86_64_sysv",
            )


def _emit_callable_body(builder, callable_decl, *, frame_layout, entry_callable_id, emit_debug_comments: bool) -> None:
    target_label, alias_labels, global_symbol = _callable_symbol_info(callable_decl, entry_callable_id=entry_callable_id)
    epilogue = epilogue_label(target_label)

    if global_symbol:
        builder.global_symbol(target_label)
    builder.label(target_label)
    for alias_label in alias_labels:
        builder.label(alias_label)

    builder.instruction("push", "rbp")
    builder.instruction("mov", "rbp", "rsp")
    if frame_layout.stack_size > 0:
        builder.instruction("sub", "rsp", str(frame_layout.stack_size))

    _emit_param_spills(builder, callable_decl, frame_layout=frame_layout)
    if emit_debug_comments:
        for slot in frame_layout.slots:
            builder.comment(f"{slot.home_name} -> {format_stack_slot_operand('rbp', slot.byte_offset)}")

    emit_straight_line_callable_body(
        builder,
        callable_decl,
        frame_layout=frame_layout,
        epilogue_label_text=epilogue,
    )

    builder.label(epilogue)
    builder.instruction("mov", "rsp", "rbp")
    builder.instruction("pop", "rbp")
    builder.instruction("ret")


def _emit_param_spills(builder, callable_decl, *, frame_layout) -> None:
    arg_locations = X86_64_SYSV_ABI.plan_argument_locations(callable_decl.signature.param_types)
    for reg_id, arg_location in zip(callable_decl.param_regs, arg_locations, strict=True):
        slot = frame_layout.for_reg(reg_id)
        if slot is None:
            raise BackendTargetLoweringError(
                f"x86_64_sysv frame layout is missing a home for parameter register 'r{reg_id.ordinal}'"
            )
        stack_operand = format_stack_slot_operand("rbp", slot.byte_offset)
        if arg_location.kind == "int_reg":
            assert arg_location.register_name is not None
            builder.instruction("mov", stack_operand, arg_location.register_name)
            continue
        if arg_location.kind == "stack":
            assert arg_location.stack_slot_index is not None
            incoming_offset = X86_64_SYSV_ABI.incoming_stack_arg_byte_offset(arg_location.stack_slot_index)
            builder.instruction("mov", "rax", f"qword ptr [rbp + {incoming_offset}]")
            builder.instruction("mov", stack_operand, "rax")
            continue
        raise BackendTargetLoweringError(f"unsupported reduced-scope parameter location kind '{arg_location.kind}'")


def _callable_symbol_info(callable_decl, *, entry_callable_id) -> tuple[str, tuple[str, ...], bool]:
    callable_id = callable_decl.callable_id
    mangled_label = mangle_function_symbol(callable_id.module_path, callable_id.name)
    if callable_id == entry_callable_id and callable_id.name == "main":
        return ("main", (mangled_label,), True)
    return (mangled_label, (), callable_decl.is_export)


def _callable_error(callable_decl, message: str) -> None:
    raise X86_64SysVLegalityError(
        f"Backend target '{TARGET_NAME}' callable '{_format_callable_id(callable_decl.callable_id)}': {message}"
    )


def _instruction_error(callable_decl, block: BackendBlock, instruction: object, message: str) -> None:
    inst_id = getattr(instruction, "inst_id", None)
    inst_name = "terminator" if inst_id is None else f"instruction 'i{inst_id.ordinal}'"
    raise X86_64SysVLegalityError(
        f"Backend target '{TARGET_NAME}' callable '{_format_callable_id(callable_decl.callable_id)}' "
        f"block 'b{block.block_id.ordinal}' {inst_name}: {message}"
    )


def _format_callable_id(callable_id) -> str:
    if isinstance(callable_id, FunctionId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.name}"
    if isinstance(callable_id, MethodId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}.{callable_id.name}"
    if isinstance(callable_id, ConstructorId):
        return f"{'.'.join(callable_id.module_path)}::{callable_id.class_name}#{callable_id.ordinal}"
    raise TypeError(f"Unsupported backend callable ID '{callable_id!r}'")


X86_64_SYSV_TARGET: BackendTarget = X86_64SysVTarget()


__all__ = [
    "TARGET_NAME",
    "X86_64_SYSV_TARGET",
    "X86_64SysVLegalityError",
    "X86_64SysVTarget",
    "check_x86_64_sysv_legality",
    "emit_x86_64_sysv_asm",
]