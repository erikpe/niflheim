from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from compiler.backend.ir import BackendRegId
from compiler.common.type_names import TYPE_NAME_DOUBLE
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_canonical_name,
    semantic_type_is_callable,
    semantic_type_is_interface,
    semantic_type_is_primitive,
    semantic_type_is_reference,
)


X86_64SysVRegisterClass = Literal["gpr", "xmm"]


@dataclass(frozen=True, slots=True)
class X86_64SysVPhysicalRegister:
    name: str
    byte_name: str | None
    register_class: X86_64SysVRegisterClass
    preserved_by_callee: bool


@dataclass(frozen=True, slots=True)
class X86_64SysVStackLocation:
    byte_offset: int
    debug_name: str


@dataclass(frozen=True, slots=True)
class X86_64SysVRegisterLocation:
    reg_id: BackendRegId
    physical_register: X86_64SysVPhysicalRegister | None
    stack_slot: X86_64SysVStackLocation | None


_GPR_BYTE_NAMES: dict[str, str] = {
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


def gpr_register(name: str, *, preserved_by_callee: bool) -> X86_64SysVPhysicalRegister:
    try:
        byte_name = _GPR_BYTE_NAMES[name]
    except KeyError as exc:
        raise ValueError(f"Unsupported x86_64 SysV GPR '{name}'") from exc
    return X86_64SysVPhysicalRegister(
        name=name,
        byte_name=byte_name,
        register_class="gpr",
        preserved_by_callee=preserved_by_callee,
    )


def xmm_register(name: str, *, preserved_by_callee: bool = False) -> X86_64SysVPhysicalRegister:
    if not _is_xmm_register_name(name):
        raise ValueError(f"Unsupported x86_64 SysV XMM register '{name}'")
    return X86_64SysVPhysicalRegister(
        name=name,
        byte_name=None,
        register_class="xmm",
        preserved_by_callee=preserved_by_callee,
    )


def _is_xmm_register_name(name: str) -> bool:
    if not name.startswith("xmm"):
        return False
    suffix = name.removeprefix("xmm")
    if not suffix.isdigit():
        return False
    return 0 <= int(suffix) <= 15


X86_64_SYSV_CALLEE_SAVED_GPRS: tuple[X86_64SysVPhysicalRegister, ...] = tuple(
    gpr_register(name, preserved_by_callee=True)
    for name in ("rbx", "r12", "r13", "r14", "r15")
)
X86_64_SYSV_CALLER_SAVED_GPRS: tuple[X86_64SysVPhysicalRegister, ...] = tuple(
    gpr_register(name, preserved_by_callee=False)
    for name in ("rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11")
)
X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS: tuple[X86_64SysVPhysicalRegister, ...] = tuple(
    gpr_register(name, preserved_by_callee=False)
    for name in ("r10", "r11")
)
X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS: tuple[X86_64SysVPhysicalRegister, ...] = tuple(
    gpr_register(name, preserved_by_callee=False)
    for name in ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
)
X86_64_SYSV_XMM_REGISTERS: tuple[X86_64SysVPhysicalRegister, ...] = tuple(
    xmm_register(f"xmm{ordinal}")
    for ordinal in range(16)
)

# Slice-1 allocation is intentionally conservative. Scratch registers remain
# outside this pool until call-clobber and scratch-conflict handling is explicit.
X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS: tuple[X86_64SysVPhysicalRegister, ...] = X86_64_SYSV_CALLEE_SAVED_GPRS


def register_class_for_type(type_ref: SemanticTypeRef) -> X86_64SysVRegisterClass:
    if semantic_type_is_primitive(type_ref):
        if semantic_type_canonical_name(type_ref) == TYPE_NAME_DOUBLE:
            return "xmm"
        return "gpr"
    if semantic_type_is_reference(type_ref) or semantic_type_is_interface(type_ref) or semantic_type_is_callable(type_ref):
        return "gpr"
    raise ValueError(f"Unsupported x86_64 SysV register type '{type_ref.display_name}'")


__all__ = [
    "X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS",
    "X86_64_SYSV_CALLEE_SAVED_GPRS",
    "X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS",
    "X86_64_SYSV_CALLER_SAVED_GPRS",
    "X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS",
    "X86_64_SYSV_XMM_REGISTERS",
    "X86_64SysVPhysicalRegister",
    "X86_64SysVRegisterClass",
    "X86_64SysVRegisterLocation",
    "X86_64SysVStackLocation",
    "gpr_register",
    "register_class_for_type",
    "xmm_register",
]
