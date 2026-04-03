from __future__ import annotations

from dataclasses import dataclass, field

from compiler.common.type_names import TYPE_NAME_OBJ
from compiler.semantic.ir import SemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_ref_for_class_id,
    semantic_type_ref_for_interface_id,
    semantic_type_canonical_name,
    semantic_type_is_array,
    semantic_type_is_interface,
    semantic_type_is_reference,
)


@dataclass(frozen=True)
class TypeCompatibilityIndex:
    implemented_interfaces_by_class_id: dict[ClassId, frozenset[InterfaceId]]
    superclass_by_class_id: dict[ClassId, ClassId] = field(default_factory=dict)


def build_type_compatibility_index(program: SemanticProgram) -> TypeCompatibilityIndex:
    implemented_interfaces_by_class_id: dict[ClassId, frozenset[InterfaceId]] = {}
    superclass_by_class_id: dict[ClassId, ClassId] = {}

    for module in program.modules.values():
        for cls in module.classes:
            implemented_interfaces_by_class_id[cls.class_id] = frozenset(cls.implemented_interfaces)
            if cls.superclass_id is not None:
                superclass_by_class_id[cls.class_id] = cls.superclass_id

    return TypeCompatibilityIndex(
        implemented_interfaces_by_class_id=implemented_interfaces_by_class_id,
        superclass_by_class_id=superclass_by_class_id,
    )


def class_is_same_or_subclass_of(
    compatibility_index: TypeCompatibilityIndex, class_id: ClassId, target_class_id: ClassId
) -> bool:
    current_class_id: ClassId | None = class_id
    while current_class_id is not None:
        if current_class_id == target_class_id:
            return True
        current_class_id = compatibility_index.superclass_by_class_id.get(current_class_id)
    return False


def class_implements_interface(
    compatibility_index: TypeCompatibilityIndex, class_id: ClassId, interface_id: InterfaceId
) -> bool:
    return interface_id in compatibility_index.implemented_interfaces_by_class_id.get(class_id, frozenset())


def is_exact_runtime_target(type_ref: SemanticTypeRef) -> bool:
    return type_ref.class_id is not None or semantic_type_is_array(type_ref)


def exact_type_implies_runtime_compatibility(
    compatibility_index: TypeCompatibilityIndex,
    exact_type_ref: SemanticTypeRef,
    target_type_ref: SemanticTypeRef,
) -> bool:
    if semantic_type_canonical_name(exact_type_ref) == semantic_type_canonical_name(target_type_ref):
        return True

    if not is_exact_runtime_target(exact_type_ref):
        return False

    if semantic_type_canonical_name(target_type_ref) == TYPE_NAME_OBJ:
        return semantic_type_is_reference(exact_type_ref) or semantic_type_is_interface(exact_type_ref)

    if exact_type_ref.class_id is not None and target_type_ref.class_id is not None:
        return class_is_same_or_subclass_of(compatibility_index, exact_type_ref.class_id, target_type_ref.class_id)

    if exact_type_ref.class_id is None or target_type_ref.interface_id is None:
        return False

    return class_implements_interface(compatibility_index, exact_type_ref.class_id, target_type_ref.interface_id)


def proven_compatible_type_names(
    compatibility_index: TypeCompatibilityIndex, target_type_ref: SemanticTypeRef
) -> frozenset[str]:
    target_type_name = semantic_type_canonical_name(target_type_ref)
    compatible_names = {target_type_name}

    if semantic_type_is_reference(target_type_ref) or semantic_type_is_interface(target_type_ref):
        compatible_names.add(TYPE_NAME_OBJ)

    if target_type_ref.class_id is not None:
        current_class_id: ClassId | None = target_type_ref.class_id
        while current_class_id is not None:
            compatible_names.add(semantic_type_canonical_name(semantic_type_ref_for_class_id(current_class_id)))
            current_class_id = compatibility_index.superclass_by_class_id.get(current_class_id)
        compatible_names.update(
            semantic_type_canonical_name(semantic_type_ref_for_interface_id(interface_id))
            for interface_id in compatibility_index.implemented_interfaces_by_class_id.get(target_type_ref.class_id, ())
        )

    return frozenset(compatible_names)
