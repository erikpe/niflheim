from __future__ import annotations

from dataclasses import dataclass

import compiler.codegen.types as codegen_types

from compiler.semantic.lowered_ir import LoweredLinkedSemanticProgram, LoweredSemanticClass, LoweredSemanticField
from compiler.semantic.symbols import ClassId, MethodId


OBJECT_FIELD_BASE_OFFSET = 24
OBJECT_FIELD_SIZE_BYTES = 8


@dataclass(frozen=True)
class EffectiveFieldSlot:
    owner_class_id: ClassId
    field: LoweredSemanticField
    offset: int


class ClassHierarchyIndex:
    def __init__(self, program: LoweredLinkedSemanticProgram) -> None:
        self._classes_by_id = {cls.class_id: cls for cls in program.classes}
        self._effective_field_slots_by_class_id: dict[ClassId, tuple[EffectiveFieldSlot, ...]] = {}

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

    def resolve_method_id(self, class_id: ClassId, method_name: str) -> MethodId:
        cls = self.class_by_id(class_id)
        for method in cls.methods:
            if method.method_id.name == method_name:
                return method.method_id

        if cls.superclass_id is not None:
            return self.resolve_method_id(cls.superclass_id, method_name)

        raise KeyError(f"Class '{class_id.name}' does not declare or inherit method '{method_name}'")