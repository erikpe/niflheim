from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendCallableDecl, BackendProgram
from compiler.semantic.symbols import ClassId, MethodId
from compiler.semantic.types import semantic_type_is_reference


OBJECT_FIELD_BASE_OFFSET = 24
OBJECT_FIELD_SIZE_BYTES = 8


@dataclass(frozen=True, slots=True)
class EffectiveFieldSlot:
    owner_class_id: ClassId
    field_name: str
    type_ref: object
    offset: int


@dataclass(frozen=True, slots=True)
class EffectiveVirtualMethodSlot:
    slot_owner_class_id: ClassId
    method_name: str
    selected_method_id: MethodId
    slot_index: int


class BackendClassHierarchyIndex:
    def __init__(self, program: BackendProgram) -> None:
        self._classes_by_id = {class_decl.class_id: class_decl for class_decl in program.classes}
        self._callables_by_id = {callable_decl.callable_id: callable_decl for callable_decl in program.callables}
        self._effective_field_slots_by_class_id: dict[ClassId, tuple[EffectiveFieldSlot, ...]] = {}
        self._effective_virtual_slots_by_class_id: dict[ClassId, tuple[EffectiveVirtualMethodSlot, ...]] = {}

    def class_by_id(self, class_id: ClassId):
        try:
            return self._classes_by_id[class_id]
        except KeyError as exc:
            raise KeyError(f"Unknown backend class id '{class_id}'") from exc

    def callable_by_id(self, callable_id):
        try:
            return self._callables_by_id[callable_id]
        except KeyError as exc:
            raise KeyError(f"Unknown backend callable id '{callable_id}'") from exc

    def effective_field_slots(self, class_id: ClassId) -> tuple[EffectiveFieldSlot, ...]:
        cached = self._effective_field_slots_by_class_id.get(class_id)
        if cached is not None:
            return cached

        class_decl = self.class_by_id(class_id)
        slots: list[EffectiveFieldSlot] = []
        if class_decl.superclass_id is not None:
            slots.extend(self.effective_field_slots(class_decl.superclass_id))

        for field in class_decl.fields:
            slots.append(
                EffectiveFieldSlot(
                    owner_class_id=class_decl.class_id,
                    field_name=field.name,
                    type_ref=field.type_ref,
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
            if semantic_type_is_reference(slot.type_ref)
        )

    def effective_virtual_slots(self, class_id: ClassId) -> tuple[EffectiveVirtualMethodSlot, ...]:
        cached = self._effective_virtual_slots_by_class_id.get(class_id)
        if cached is not None:
            return cached

        class_decl = self.class_by_id(class_id)
        slots = [] if class_decl.superclass_id is None else list(self.effective_virtual_slots(class_decl.superclass_id))
        slot_indices_by_name = {slot.method_name: index for index, slot in enumerate(slots)}

        for method_id in class_decl.methods:
            callable_decl = self.callable_by_id(method_id)
            if not _is_virtual_method(callable_decl):
                continue

            existing_index = slot_indices_by_name.get(method_id.name)
            if existing_index is None:
                slot_index = len(slots)
                slots.append(
                    EffectiveVirtualMethodSlot(
                        slot_owner_class_id=class_decl.class_id,
                        method_name=method_id.name,
                        selected_method_id=method_id,
                        slot_index=slot_index,
                    )
                )
                slot_indices_by_name[method_id.name] = slot_index
                continue

            inherited_slot = slots[existing_index]
            slots[existing_index] = EffectiveVirtualMethodSlot(
                slot_owner_class_id=inherited_slot.slot_owner_class_id,
                method_name=inherited_slot.method_name,
                selected_method_id=method_id,
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
            f"Class '{class_id.name}' has no backend virtual slot '{slot_owner_class_id.name}.{method_name}'"
        )

    def resolve_virtual_method_id(self, class_id: ClassId, slot_owner_class_id: ClassId, method_name: str) -> MethodId:
        for slot in self.effective_virtual_slots(class_id):
            if slot.slot_owner_class_id == slot_owner_class_id and slot.method_name == method_name:
                return slot.selected_method_id
        raise KeyError(
            f"Class '{class_id.name}' has no backend virtual slot '{slot_owner_class_id.name}.{method_name}'"
        )

    def resolve_method_id(self, class_id: ClassId, method_name: str) -> MethodId:
        for slot in self.effective_virtual_slots(class_id):
            if slot.method_name == method_name:
                return slot.selected_method_id

        class_decl = self.class_by_id(class_id)
        for method_id in class_decl.methods:
            if method_id.name == method_name:
                return method_id

        if class_decl.superclass_id is not None:
            return self.resolve_method_id(class_decl.superclass_id, method_name)

        raise KeyError(f"Class '{class_id.name}' does not declare or inherit method '{method_name}'")


def _is_virtual_method(callable_decl: BackendCallableDecl) -> bool:
    return callable_decl.kind == "method" and callable_decl.is_static is False and callable_decl.is_private is False


__all__ = [
    "BackendClassHierarchyIndex",
    "EffectiveFieldSlot",
    "EffectiveVirtualMethodSlot",
    "OBJECT_FIELD_BASE_OFFSET",
    "OBJECT_FIELD_SIZE_BYTES",
]