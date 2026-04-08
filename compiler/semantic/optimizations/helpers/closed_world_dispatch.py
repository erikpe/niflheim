from __future__ import annotations

from dataclasses import dataclass

from compiler.semantic.ir import SemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceMethodId, MethodId

from .interface_dispatch import InterfaceDispatchIndex
from .type_compatibility import TypeCompatibilityIndex


@dataclass(frozen=True)
class ClosedWorldDispatchIndex:
    monomorphic_interface_method_by_interface_method_id: dict[InterfaceMethodId, MethodId]
    monomorphic_virtual_method_by_receiver_and_slot: dict[tuple[ClassId, ClassId, str], MethodId]


def build_closed_world_dispatch_index(
    program: SemanticProgram,
    compatibility_index: TypeCompatibilityIndex,
    interface_dispatch_index: InterfaceDispatchIndex,
) -> ClosedWorldDispatchIndex:
    classes_by_id = {
        cls.class_id: cls
        for module in program.modules.values()
        for cls in module.classes
    }
    direct_subclasses_by_class_id: dict[ClassId, set[ClassId]] = {}
    for class_id, superclass_id in compatibility_index.superclass_by_class_id.items():
        direct_subclasses_by_class_id.setdefault(superclass_id, set()).add(class_id)

    descendants_by_class_id: dict[ClassId, tuple[ClassId, ...]] = {}
    effective_virtual_slots_by_class_id: dict[ClassId, tuple[_EffectiveVirtualSlot, ...]] = {}

    def descendant_class_ids(class_id: ClassId) -> tuple[ClassId, ...]:
        cached = descendants_by_class_id.get(class_id)
        if cached is not None:
            return cached

        descendants = [class_id]
        for child_class_id in sorted(direct_subclasses_by_class_id.get(class_id, ()), key=_class_sort_key):
            descendants.extend(descendant_class_ids(child_class_id))

        cached = tuple(descendants)
        descendants_by_class_id[class_id] = cached
        return cached

    def effective_virtual_slots(class_id: ClassId) -> tuple[_EffectiveVirtualSlot, ...]:
        cached = effective_virtual_slots_by_class_id.get(class_id)
        if cached is not None:
            return cached

        cls = classes_by_id[class_id]
        slots = [] if cls.superclass_id is None else list(effective_virtual_slots(cls.superclass_id))
        slot_indices_by_name = {slot.method_name: index for index, slot in enumerate(slots)}

        for method in cls.methods:
            if method.is_static or method.is_private:
                continue

            existing_index = slot_indices_by_name.get(method.method_id.name)
            if existing_index is None:
                slot_indices_by_name[method.method_id.name] = len(slots)
                slots.append(
                    _EffectiveVirtualSlot(
                        slot_owner_class_id=cls.class_id,
                        method_name=method.method_id.name,
                        selected_method_id=method.method_id,
                    )
                )
                continue

            inherited_slot = slots[existing_index]
            slots[existing_index] = _EffectiveVirtualSlot(
                slot_owner_class_id=inherited_slot.slot_owner_class_id,
                method_name=inherited_slot.method_name,
                selected_method_id=method.method_id,
            )

        cached = tuple(slots)
        effective_virtual_slots_by_class_id[class_id] = cached
        return cached

    monomorphic_interface_method_by_interface_method_id: dict[InterfaceMethodId, MethodId] = {}
    methods_by_interface_method_id: dict[InterfaceMethodId, set[MethodId]] = {}
    for (_, interface_method_id), method_id in interface_dispatch_index.implementing_method_by_class_and_interface_method.items():
        methods_by_interface_method_id.setdefault(interface_method_id, set()).add(method_id)

    for interface_method_id, method_ids in methods_by_interface_method_id.items():
        if len(method_ids) == 1:
            monomorphic_interface_method_by_interface_method_id[interface_method_id] = next(iter(method_ids))

    monomorphic_virtual_method_by_receiver_and_slot: dict[tuple[ClassId, ClassId, str], MethodId] = {}
    for receiver_class_id in classes_by_id:
        for slot in effective_virtual_slots(receiver_class_id):
            reachable_method_ids = {
                descendant_slot.selected_method_id
                for descendant_class_id in descendant_class_ids(receiver_class_id)
                for descendant_slot in effective_virtual_slots(descendant_class_id)
                if descendant_slot.slot_owner_class_id == slot.slot_owner_class_id
                and descendant_slot.method_name == slot.method_name
            }
            if len(reachable_method_ids) != 1:
                continue
            monomorphic_virtual_method_by_receiver_and_slot[
                (receiver_class_id, slot.slot_owner_class_id, slot.method_name)
            ] = next(iter(reachable_method_ids))

    return ClosedWorldDispatchIndex(
        monomorphic_interface_method_by_interface_method_id=monomorphic_interface_method_by_interface_method_id,
        monomorphic_virtual_method_by_receiver_and_slot=monomorphic_virtual_method_by_receiver_and_slot,
    )


def resolve_closed_world_interface_method(
    closed_world_index: ClosedWorldDispatchIndex,
    interface_method_id: InterfaceMethodId,
) -> MethodId | None:
    return closed_world_index.monomorphic_interface_method_by_interface_method_id.get(interface_method_id)


def resolve_closed_world_virtual_method(
    closed_world_index: ClosedWorldDispatchIndex,
    receiver_class_id: ClassId,
    slot_owner_class_id: ClassId,
    method_name: str,
) -> MethodId | None:
    return closed_world_index.monomorphic_virtual_method_by_receiver_and_slot.get(
        (receiver_class_id, slot_owner_class_id, method_name)
    )


@dataclass(frozen=True)
class _EffectiveVirtualSlot:
    slot_owner_class_id: ClassId
    method_name: str
    selected_method_id: MethodId


def _class_sort_key(class_id: ClassId) -> tuple[tuple[str, ...], str]:
    return class_id.module_path, class_id.name