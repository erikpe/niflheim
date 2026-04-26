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
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder
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

    if any(not callable_decl.is_extern and callable_decl.blocks for callable_decl in target_input.program.callables):
        raise BackendTargetLoweringError(
            "x86_64_sysv target scaffold is present, but frame and instruction emission land in later phase-4 slices"
        )

    builder = X86AsmBuilder(emit_debug_comments=options.emit_debug_comments)
    if options.emit_debug_comments:
        builder.comment("x86_64_sysv target scaffold validated an extern-only program")
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
        if instruction.effects != type(instruction.effects)():
            _instruction_error(
                callable_decl,
                block,
                instruction,
                "call effects must be empty in reduced phase-4 x86_64_sysv",
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