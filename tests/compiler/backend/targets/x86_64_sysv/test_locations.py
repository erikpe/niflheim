from __future__ import annotations

import pytest

from compiler.backend.targets.x86_64_sysv import (
    X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS,
    X86_64_SYSV_CALLEE_SAVED_GPRS,
    X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS,
    X86_64_SYSV_CALLER_SAVED_GPRS,
    X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS,
    X86_64_SYSV_RETURN_ALLOCATABLE_GPRS,
    X86_64_SYSV_XMM_REGISTERS,
    gpr_register,
    register_class_for_type,
    xmm_register,
)
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import SemanticTypeRef, semantic_primitive_type_ref


def test_gpr_register_metadata_includes_byte_name_and_preservation() -> None:
    assert gpr_register("rbx", preserved_by_callee=True).name == "rbx"
    assert gpr_register("rbx", preserved_by_callee=True).byte_name == "bl"
    assert gpr_register("r12", preserved_by_callee=True).byte_name == "r12b"
    assert gpr_register("r11", preserved_by_callee=False).byte_name == "r11b"
    assert gpr_register("rbx", preserved_by_callee=True).register_class == "gpr"
    assert gpr_register("rbx", preserved_by_callee=True).preserved_by_callee is True
    assert gpr_register("r11", preserved_by_callee=False).preserved_by_callee is False


def test_xmm_register_metadata_has_no_byte_name() -> None:
    register = xmm_register("xmm15")

    assert register.name == "xmm15"
    assert register.byte_name is None
    assert register.register_class == "xmm"
    assert register.preserved_by_callee is False


@pytest.mark.parametrize("name", ["rsp", "rbp", "eax", "xmm0"])
def test_gpr_register_rejects_non_allocatable_or_non_gpr_names(name: str) -> None:
    with pytest.raises(ValueError, match="Unsupported x86_64 SysV GPR"):
        gpr_register(name, preserved_by_callee=False)


@pytest.mark.parametrize("name", ["xmm16", "xmm", "rax"])
def test_xmm_register_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="Unsupported x86_64 SysV XMM register"):
        xmm_register(name)


def test_register_pools_are_deterministic_and_distinct() -> None:
    assert tuple(register.name for register in X86_64_SYSV_CALLEE_SAVED_GPRS) == (
        "rbx",
        "r12",
        "r13",
        "r14",
        "r15",
    )
    assert tuple(register.name for register in X86_64_SYSV_INITIAL_ALLOCATABLE_GPRS) == (
        "rbx",
        "r12",
        "r13",
        "r14",
        "r15",
    )
    assert tuple(register.name for register in X86_64_SYSV_CALLER_SAVED_GPRS) == (
        "rax",
        "rcx",
        "rdx",
        "rsi",
        "rdi",
        "r8",
        "r9",
        "r10",
        "r11",
    )
    assert tuple(register.name for register in X86_64_SYSV_CALL_FREE_ALLOCATABLE_GPRS) == ("r10", "r11")
    assert tuple(register.name for register in X86_64_SYSV_ARGUMENT_ALLOCATABLE_GPRS) == (
        "rdi",
        "rsi",
        "rdx",
        "rcx",
        "r8",
        "r9",
    )
    assert tuple(register.name for register in X86_64_SYSV_RETURN_ALLOCATABLE_GPRS) == ("rax",)
    assert tuple(register.name for register in X86_64_SYSV_XMM_REGISTERS[:4]) == ("xmm0", "xmm1", "xmm2", "xmm3")
    assert tuple(register.name for register in X86_64_SYSV_XMM_REGISTERS[-2:]) == ("xmm14", "xmm15")


@pytest.mark.parametrize("type_name", [TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_BOOL])
def test_register_class_for_integer_like_primitive_types_is_gpr(type_name: str) -> None:
    assert register_class_for_type(semantic_primitive_type_ref(type_name)) == "gpr"


def test_register_class_for_double_is_xmm() -> None:
    assert register_class_for_type(semantic_primitive_type_ref(TYPE_NAME_DOUBLE)) == "xmm"


def test_register_class_for_reference_interface_and_callable_types_is_gpr() -> None:
    object_ref = SemanticTypeRef(kind="reference", canonical_name="Obj", display_name="Obj")
    interface_ref = SemanticTypeRef(kind="interface", canonical_name="Readable", display_name="Readable")
    callable_ref = SemanticTypeRef(
        kind="callable",
        canonical_name="fn(i64) -> bool",
        display_name="fn(i64) -> bool",
        param_types=(semantic_primitive_type_ref(TYPE_NAME_I64),),
        return_type=semantic_primitive_type_ref(TYPE_NAME_BOOL),
    )

    assert register_class_for_type(object_ref) == "gpr"
    assert register_class_for_type(interface_ref) == "gpr"
    assert register_class_for_type(callable_ref) == "gpr"
