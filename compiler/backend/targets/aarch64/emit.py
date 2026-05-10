from __future__ import annotations

from compiler.backend.targets import (
    BackendEmitResult,
    BackendTargetInput,
    BackendTargetLoweringError,
    BackendTargetOptions,
)
from compiler.backend.targets.aarch64.abi import AARCH64_ABI


TARGET_NAME = "aarch64"


class AArch64LegalityError(BackendTargetLoweringError):
    """Raised when backend IR falls outside the current AArch64 target scaffold."""


class AArch64Target:
    name = TARGET_NAME

    def emit_assembly(self, target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
        return emit_aarch64_asm(target_input, options=options)


def emit_aarch64_asm(target_input: BackendTargetInput, *, options: BackendTargetOptions) -> BackendEmitResult:
    del options
    check_aarch64_legality(target_input)
    raise AArch64LegalityError("aarch64 assembly emission is not implemented yet")


def check_aarch64_legality(target_input: BackendTargetInput) -> None:
    for callable_decl in target_input.program.callables:
        _check_callable_shape(callable_decl)
        _check_callable_signature(callable_decl)
        _check_callable_register_types(callable_decl)
        target_input.analysis_for_callable(callable_decl.callable_id)


def _check_callable_shape(callable_decl) -> None:
    if callable_decl.kind == "function":
        if callable_decl.receiver_reg is not None:
            raise AArch64LegalityError("functions must not declare a receiver register")
        return
    if callable_decl.kind == "method":
        if callable_decl.is_static is True and callable_decl.receiver_reg is None:
            return
        if callable_decl.is_static is False and callable_decl.receiver_reg is not None:
            return
        raise AArch64LegalityError("methods must either be static without a receiver or instance methods with one")
    if callable_decl.kind == "constructor":
        if callable_decl.receiver_reg is None:
            raise AArch64LegalityError("constructors must declare a receiver register")
        return
    raise AArch64LegalityError(f"unsupported callable kind '{callable_decl.kind}'")


def _check_callable_signature(callable_decl) -> None:
    for param_type in callable_decl.signature.param_types:
        if not AARCH64_ABI.supports_passed_type(param_type):
            raise AArch64LegalityError(
                f"unsupported aarch64 parameter type '{param_type.display_name}'"
            )
    if not AARCH64_ABI.supports_passed_type(callable_decl.signature.return_type):
        assert callable_decl.signature.return_type is not None
        raise AArch64LegalityError(
            f"unsupported aarch64 return type '{callable_decl.signature.return_type.display_name}'"
        )


def _check_callable_register_types(callable_decl) -> None:
    for register in callable_decl.registers:
        if not AARCH64_ABI.supports_passed_type(register.type_ref):
            raise AArch64LegalityError(
                f"register 'r{register.reg_id.ordinal}' uses unsupported aarch64 type '{register.type_ref.display_name}'"
            )


AARCH64_TARGET = AArch64Target()


__all__ = [
    "AARCH64_TARGET",
    "AArch64LegalityError",
    "AArch64Target",
    "TARGET_NAME",
    "check_aarch64_legality",
    "emit_aarch64_asm",
]