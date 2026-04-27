from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_canonical_name,
    semantic_type_is_interface,
    semantic_type_is_primitive,
    semantic_type_is_reference,
)


@dataclass(frozen=True, slots=True)
class X86_64SysVArgLocation:
    kind: str
    register_name: str | None = None
    stack_slot_index: int | None = None


@dataclass(frozen=True, slots=True)
class X86_64SysVAbi:
    int_arg_registers: tuple[str, ...] = ("rdi", "rsi", "rdx", "rcx", "r8", "r9")
    float_arg_registers: tuple[str, ...] = ("xmm0", "xmm1", "xmm2", "xmm3", "xmm4", "xmm5", "xmm6", "xmm7")
    int_return_register: str = "rax"
    float_return_register: str = "xmm0"
    caller_saved_registers: tuple[str, ...] = ("rax", "rcx", "rdx", "rsi", "rdi", "r8", "r9", "r10", "r11")
    callee_saved_registers: tuple[str, ...] = ("rbx", "r12", "r13", "r14", "r15")
    frame_pointer_register: str = "rbp"
    stack_pointer_register: str = "rsp"
    stack_alignment_bytes: int = 16
    stack_slot_size_bytes: int = 8
    incoming_stack_arg_base_offset: int = 16
    supported_scalar_type_names: frozenset[str] = frozenset({TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_BOOL, TYPE_NAME_DOUBLE})

    def supports_scalar_type(self, type_ref: SemanticTypeRef | None) -> bool:
        if type_ref is None:
            return True
        return semantic_type_is_primitive(type_ref) and type_ref.canonical_name in self.supported_scalar_type_names

    def supports_passed_type(self, type_ref: SemanticTypeRef | None) -> bool:
        if type_ref is None:
            return True
        if self.supports_scalar_type(type_ref):
            return True
        return semantic_type_is_reference(type_ref) or semantic_type_is_interface(type_ref)

    def is_float_type(self, type_ref: SemanticTypeRef | None) -> bool:
        return type_ref is not None and semantic_type_canonical_name(type_ref) == TYPE_NAME_DOUBLE

    def plan_argument_locations(
        self,
        param_types: tuple[SemanticTypeRef, ...],
        *,
        includes_receiver: bool = False,
    ) -> tuple[X86_64SysVArgLocation, ...]:
        locations: list[X86_64SysVArgLocation] = []
        int_arg_index = 0
        float_arg_index = 0
        stack_slot_index = 0
        if includes_receiver:
            if int_arg_index < len(self.int_arg_registers):
                locations.append(X86_64SysVArgLocation(kind="int_reg", register_name=self.int_arg_registers[int_arg_index]))
                int_arg_index += 1
            else:
                locations.append(X86_64SysVArgLocation(kind="stack", stack_slot_index=stack_slot_index))
                stack_slot_index += 1
        for param_type in param_types:
            if not self.supports_passed_type(param_type):
                raise ValueError(f"Unsupported SysV passed parameter type '{param_type.display_name}'")
            if self.is_float_type(param_type):
                if float_arg_index < len(self.float_arg_registers):
                    locations.append(
                        X86_64SysVArgLocation(kind="float_reg", register_name=self.float_arg_registers[float_arg_index])
                    )
                    float_arg_index += 1
                    continue
                locations.append(X86_64SysVArgLocation(kind="stack", stack_slot_index=stack_slot_index))
                stack_slot_index += 1
                continue
            if int_arg_index < len(self.int_arg_registers):
                locations.append(X86_64SysVArgLocation(kind="int_reg", register_name=self.int_arg_registers[int_arg_index]))
                int_arg_index += 1
                continue
            locations.append(X86_64SysVArgLocation(kind="stack", stack_slot_index=stack_slot_index))
            stack_slot_index += 1
        return tuple(locations)

    def return_register_for_type(self, type_ref: SemanticTypeRef | None) -> str | None:
        if type_ref is None:
            return None
        if not self.supports_passed_type(type_ref):
            raise ValueError(f"Unsupported SysV passed return type '{type_ref.display_name}'")
        if self.is_float_type(type_ref):
            return self.float_return_register
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

    def incoming_stack_arg_byte_offset(self, stack_slot_index: int) -> int:
        if stack_slot_index < 0:
            raise ValueError("Incoming stack argument slot index must be non-negative")
        return self.incoming_stack_arg_base_offset + (stack_slot_index * self.stack_slot_size_bytes)

    def outgoing_stack_arg_slot_count(
        self,
        param_types: tuple[SemanticTypeRef, ...],
        *,
        includes_receiver: bool = False,
    ) -> int:
        return sum(
            1
            for location in self.plan_argument_locations(param_types, includes_receiver=includes_receiver)
            if location.kind == "stack"
        )

    def call_stack_reservation_bytes(self, stack_arg_slot_count: int) -> int:
        if stack_arg_slot_count < 0:
            raise ValueError("Outgoing stack argument slot count must be non-negative")
        if stack_arg_slot_count == 0:
            return 0
        return self.align_stack_size(stack_arg_slot_count * self.stack_slot_size_bytes)


X86_64_SYSV_ABI = X86_64SysVAbi()


__all__ = ["X86_64_SYSV_ABI", "X86_64SysVAbi", "X86_64SysVArgLocation"]