from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import SemanticTypeRef, semantic_type_is_primitive


@dataclass(frozen=True, slots=True)
class X86_64SysVArgLocation:
    kind: str
    register_name: str | None = None
    stack_slot_index: int | None = None


@dataclass(frozen=True, slots=True)
class X86_64SysVAbi:
    int_arg_registers: tuple[str, ...] = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
    int_return_register: str = "rax"
    caller_saved_registers: tuple[str, ...] = ("rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11")
    callee_saved_registers: tuple[str, ...] = ("rbx", "r12", "r13", "r14", "r15")
    frame_pointer_register: str = "rbp"
    stack_pointer_register: str = "rsp"
    stack_alignment_bytes: int = 16
    stack_slot_size_bytes: int = 8
    supported_scalar_type_names: frozenset[str] = frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_BOOL})

    def supports_scalar_type(self, type_ref: SemanticTypeRef | None) -> bool:
        if type_ref is None:
            return True
        return semantic_type_is_primitive(type_ref) and type_ref.canonical_name in self.supported_scalar_type_names

    def plan_argument_locations(self, param_types: tuple[SemanticTypeRef, ...]) -> tuple[X86_64SysVArgLocation, ...]:
        locations: list[X86_64SysVArgLocation] = []
        for index, param_type in enumerate(param_types):
            if not self.supports_scalar_type(param_type):
                raise ValueError(f"Unsupported reduced-scope SysV parameter type '{param_type.display_name}'")
            if index < len(self.int_arg_registers):
                locations.append(X86_64SysVArgLocation(kind="int_reg", register_name=self.int_arg_registers[index]))
                continue
            locations.append(
                X86_64SysVArgLocation(
                    kind="stack",
                    stack_slot_index=index - len(self.int_arg_registers),
                )
            )
        return tuple(locations)

    def return_register_for_type(self, type_ref: SemanticTypeRef | None) -> str | None:
        if type_ref is None:
            return None
        if not self.supports_scalar_type(type_ref):
            raise ValueError(f"Unsupported reduced-scope SysV return type '{type_ref.display_name}'")
        return self.int_return_register

    def stack_size_is_aligned(self, byte_count: int) -> bool:
        if byte_count < 0:
            raise ValueError("Stack byte count must be non-negative")
        return byte_count % self.stack_alignment_bytes == 0

    def align_stack_size(self, byte_count: int) -> int:
        if byte_count < 0:
            raise ValueError("Stack byte count must be non-negative")
        remainder = byte_count % self.stack_alignment_bytes
        if remainder == 0:
            return byte_count
        return byte_count + (self.stack_alignment_bytes - remainder)


X86_64_SYSV_ABI = X86_64SysVAbi()


__all__ = ["X86_64_SYSV_ABI", "X86_64SysVAbi", "X86_64SysVArgLocation"]