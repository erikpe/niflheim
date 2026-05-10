"""AArch64 backend target scaffold."""

from compiler.backend.targets.aarch64.abi import AARCH64_ABI, AArch64Abi, AArch64ArgLocation
from compiler.backend.targets.aarch64.asm import AArch64AsmBuilder, format_stack_slot_operand
from compiler.backend.targets.aarch64.emit import (
    AARCH64_TARGET,
    AArch64LegalityError,
    AArch64Target,
    TARGET_NAME,
    check_aarch64_legality,
    emit_aarch64_asm,
)
from compiler.backend.targets.aarch64.frame import (
    AArch64FrameError,
    AArch64FrameLayout,
    AArch64FrameSlot,
    AArch64RootSlot,
    plan_callable_frame_layout,
)

__all__ = [
    "AARCH64_ABI",
    "AARCH64_TARGET",
    "AArch64Abi",
    "AArch64ArgLocation",
    "AArch64AsmBuilder",
    "AArch64FrameError",
    "AArch64FrameLayout",
    "AArch64FrameSlot",
    "AArch64LegalityError",
    "AArch64RootSlot",
    "AArch64Target",
    "TARGET_NAME",
    "check_aarch64_legality",
    "emit_aarch64_asm",
    "format_stack_slot_operand",
    "plan_callable_frame_layout",
]