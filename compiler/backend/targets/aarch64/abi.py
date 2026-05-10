from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_canonical_name,
    semantic_type_is_callable,
    semantic_type_is_interface,
    semantic_type_is_primitive,
    semantic_type_is_reference,
)


@dataclass(frozen=True, slots=True)
class AArch64ArgLocation:
    kind: str
    register_name: str | None = None
    stack_slot_index: int | None = None


@dataclass(frozen=True, slots=True)
class AArch64Abi:
    int_arg_registers: tuple[str, ...] = ("x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7")
    float_arg_registers: tuple[str, ...] = ("d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7")
    int_return_register: str = "x0"
    float_return_register: str = "d0"
    caller_saved_registers: tuple[str, ...] = (
        "x0",
        "x1",
        "x2",
        "x3",
        "x4",
        "x5",
        "x6",
        "x7",
        "x8",
        "x9",
        "x10",
        "x11",
        "x12",
        "x13",
        "x14",
        "x15",
        "x16",
        "x17",
    )
    callee_saved_registers: tuple[str, ...] = ("x19", "x20", "x21", "x22", "x23", "x24", "x25", "x26", "x27", "x28")
    callee_saved_float_registers: tuple[str, ...] = ("d8", "d9", "d10", "d11", "d12", "d13", "d14", "d15")
    frame_pointer_register: str = "x29"
    link_register: str = "x30"
    stack_pointer_register: str = "sp"
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
        return semantic_type_is_reference(type_ref) or semantic_type_is_interface(type_ref) or semantic_type_is_callable(type_ref)

    def is_float_type(self, type_ref: SemanticTypeRef | None) -> bool:
        return type_ref is not None and semantic_type_canonical_name(type_ref) == TYPE_NAME_DOUBLE

    def plan_argument_locations(
        self,
        param_types: tuple[SemanticTypeRef, ...],
        *,
        includes_receiver: bool = False,
    ) -> tuple[AArch64ArgLocation, ...]:
        locations: list[AArch64ArgLocation] = []
        int_arg_index = 0
        float_arg_index = 0
        stack_slot_index = 0
        if includes_receiver:
            if int_arg_index < len(self.int_arg_registers):
                locations.append(AArch64ArgLocation(kind="int_reg", register_name=self.int_arg_registers[int_arg_index]))
                int_arg_index += 1
            else:
                locations.append(AArch64ArgLocation(kind="stack", stack_slot_index=stack_slot_index))
                stack_slot_index += 1
        for param_type in param_types:
            if not self.supports_passed_type(param_type):
                raise ValueError(f"Unsupported AArch64 passed parameter type '{param_type.display_name}'")
            if self.is_float_type(param_type):
                if float_arg_index < len(self.float_arg_registers):
                    locations.append(AArch64ArgLocation(kind="float_reg", register_name=self.float_arg_registers[float_arg_index]))
                    float_arg_index += 1
                    continue
                locations.append(AArch64ArgLocation(kind="stack", stack_slot_index=stack_slot_index))
                stack_slot_index += 1
                continue
            if int_arg_index < len(self.int_arg_registers):
                locations.append(AArch64ArgLocation(kind="int_reg", register_name=self.int_arg_registers[int_arg_index]))
                int_arg_index += 1
                continue
            locations.append(AArch64ArgLocation(kind="stack", stack_slot_index=stack_slot_index))
            stack_slot_index += 1
        return tuple(locations)

    def return_register_for_type(self, type_ref: SemanticTypeRef | None) -> str | None:
        if type_ref is None:
            return None
        if not self.supports_passed_type(type_ref):
            raise ValueError(f"Unsupported AArch64 passed return type '{type_ref.display_name}'")
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


AARCH64_ABI = AArch64Abi()


__all__ = ["AARCH64_ABI", "AArch64Abi", "AArch64ArgLocation"]