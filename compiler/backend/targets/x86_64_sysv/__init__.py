"""Reduced-scope x86-64 SysV backend target surface."""

from compiler.backend.targets.x86_64_sysv.abi import (
    X86_64_SYSV_ABI,
    X86_64SysVAbi,
    X86_64SysVArgLocation,
)
from compiler.backend.targets.x86_64_sysv.asm import X86AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.x86_64_sysv.frame import (
    X86_64SysVFrameError,
    X86_64SysVFrameLayout,
    X86_64SysVFrameSlot,
    plan_callable_frame_layout,
)
from compiler.backend.targets.x86_64_sysv.emit import (
    TARGET_NAME,
    X86_64_SYSV_TARGET,
    X86_64SysVLegalityError,
    X86_64SysVTarget,
    check_x86_64_sysv_legality,
    emit_x86_64_sysv_asm,
)

__all__ = [
    "TARGET_NAME",
    "X86_64_SYSV_ABI",
    "X86_64_SYSV_TARGET",
    "X86AsmBuilder",
    "X86_64SysVAbi",
    "X86_64SysVArgLocation",
    "X86_64SysVFrameError",
    "X86_64SysVFrameLayout",
    "X86_64SysVFrameSlot",
    "X86_64SysVLegalityError",
    "X86_64SysVTarget",
    "check_x86_64_sysv_legality",
    "emit_x86_64_sysv_asm",
    "format_stack_slot_operand",
    "plan_callable_frame_layout",
]