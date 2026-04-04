from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.types as codegen_types

from compiler.semantic.lowered_ir import (
    LoweredLinkedSemanticProgram,
    LoweredSemanticClass,
    LoweredSemanticField,
    LoweredSemanticMethod,
)
from compiler.semantic.symbols import ClassId, MethodId


OBJECT_FIELD_BASE_OFFSET = 24
OBJECT_FIELD_SIZE_BYTES = 8


@dataclass(frozen=True)
class EffectiveFieldSlot:
    owner_class_id: ClassId
    field: LoweredSemanticField
    offset: int


@dataclass(frozen=True)
class EffectiveVirtualMethodSlot:
    slot_owner_class_id: ClassId
    method_name: str
    selected_method_id: MethodId
    slot_index: int


class ClassHierarchyIndex:
    def __init__(self, program: LoweredLinkedSemanticProgram) -> None:
        self._classes_by_id = {cls.class_id: cls for cls in program.classes}
        self._effective_field_slots_by_class_id: dict[ClassId, tuple[EffectiveFieldSlot, ...]] = {}
        self._effective_virtual_slots_by_class_id: dict[ClassId, tuple[EffectiveVirtualMethodSlot, ...]] = {}

    def class_by_id(self, class_id: ClassId) -> LoweredSemanticClass:
        cls = self._classes_by_id.get(class_id)
        if cls is None:
            raise KeyError(f"Unknown class id '{class_id}'")
        return cls

    def effective_field_slots(self, class_id: ClassId) -> tuple[EffectiveFieldSlot, ...]:
        cached = self._effective_field_slots_by_class_id.get(class_id)
        if cached is not None:
            return cached

        cls = self.class_by_id(class_id)
        slots: list[EffectiveFieldSlot] = []
        if cls.superclass_id is not None:
            slots.extend(self.effective_field_slots(cls.superclass_id))

        for field in cls.fields:
            slots.append(
                EffectiveFieldSlot(
                    owner_class_id=cls.class_id,
                    field=field,
                    offset=OBJECT_FIELD_BASE_OFFSET + (len(slots) * OBJECT_FIELD_SIZE_BYTES),
                )
            )

        result = tuple(slots)
        self._effective_field_slots_by_class_id[class_id] = result
        return result

    def payload_bytes(self, class_id: ClassId) -> int:
        return len(self.effective_field_slots(class_id)) * OBJECT_FIELD_SIZE_BYTES

    def pointer_offsets(self, class_id: ClassId) -> tuple[int, ...]:
        return tuple(
            slot.offset
            for slot in self.effective_field_slots(class_id)
            if codegen_types.is_reference_type_ref(slot.field.type_ref)
        )

    def effective_virtual_slots(self, class_id: ClassId) -> tuple[EffectiveVirtualMethodSlot, ...]:
        cached = self._effective_virtual_slots_by_class_id.get(class_id)
        if cached is not None:
            return cached

        cls = self.class_by_id(class_id)
        slots = [] if cls.superclass_id is None else list(self.effective_virtual_slots(cls.superclass_id))
        slot_indices_by_name = {slot.method_name: index for index, slot in enumerate(slots)}

        for method in cls.methods:
            if not _is_virtual_method(method):
                continue

            existing_index = slot_indices_by_name.get(method.method_id.name)
            if existing_index is None:
                slot_index = len(slots)
                slots.append(
                    EffectiveVirtualMethodSlot(
                        slot_owner_class_id=cls.class_id,
                        method_name=method.method_id.name,
                        selected_method_id=method.method_id,
                        slot_index=slot_index,
                    )
                )
                slot_indices_by_name[method.method_id.name] = slot_index
                continue

            inherited_slot = slots[existing_index]
            slots[existing_index] = EffectiveVirtualMethodSlot(
                slot_owner_class_id=inherited_slot.slot_owner_class_id,
                method_name=inherited_slot.method_name,
                selected_method_id=method.method_id,
                slot_index=inherited_slot.slot_index,
            )

        result = tuple(slots)
        self._effective_virtual_slots_by_class_id[class_id] = result
        return result

    def resolve_virtual_slot_index(self, class_id: ClassId, slot_owner_class_id: ClassId, method_name: str) -> int:
        for slot in self.effective_virtual_slots(class_id):
            if slot.slot_owner_class_id == slot_owner_class_id and slot.method_name == method_name:
                return slot.slot_index
        raise KeyError(
            f"Class '{class_id.name}' has no virtual slot '{slot_owner_class_id.name}.{method_name}'"
        )

    def resolve_virtual_method_id(self, class_id: ClassId, slot_owner_class_id: ClassId, method_name: str) -> MethodId:
        for slot in self.effective_virtual_slots(class_id):
            if slot.slot_owner_class_id == slot_owner_class_id and slot.method_name == method_name:
                return slot.selected_method_id
        raise KeyError(
            f"Class '{class_id.name}' has no virtual slot '{slot_owner_class_id.name}.{method_name}'"
        )

    def resolve_method_id(self, class_id: ClassId, method_name: str) -> MethodId:
        for slot in self.effective_virtual_slots(class_id):
            if slot.method_name == method_name:
                return slot.selected_method_id

        cls = self.class_by_id(class_id)
        for method in cls.methods:
            if method.method_id.name == method_name:
                return method.method_id

        if cls.superclass_id is not None:
            return self.resolve_method_id(cls.superclass_id, method_name)

        raise KeyError(f"Class '{class_id.name}' does not declare or inherit method '{method_name}'")


def _is_virtual_method(method: LoweredSemanticMethod) -> bool:
    return not method.is_static and not method.is_private