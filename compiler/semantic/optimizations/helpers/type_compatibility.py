from __future__ import annotations

from dataclasses import dataclass

from compiler.common.type_names import TYPE_NAME_OBJ
from compiler.semantic.ir import SemanticProgram
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_canonical_name,
    semantic_type_is_array,
    semantic_type_is_interface,
    semantic_type_is_reference,
)


@dataclass(frozen=True)
class TypeCompatibilityIndex:
    implemented_interfaces_by_class_name: dict[str, frozenset[str]]


def build_type_compatibility_index(program: SemanticProgram) -> TypeCompatibilityIndex:
    implemented_interfaces_by_class_name: dict[str, frozenset[str]] = {}

    for module in program.modules.values():
        for cls in module.classes:
            class_name = f"{'.'.join(cls.class_id.module_path)}::{cls.class_id.name}"
            implemented_interfaces_by_class_name[class_name] = frozenset(
                f"{'.'.join(interface_id.module_path)}::{interface_id.name}"
                for interface_id in cls.implemented_interfaces
            )

    return TypeCompatibilityIndex(implemented_interfaces_by_class_name=implemented_interfaces_by_class_name)


def is_exact_runtime_target(type_ref: SemanticTypeRef) -> bool:
    return type_ref.class_id is not None or semantic_type_is_array(type_ref)


def proven_compatible_type_names(
    compatibility_index: TypeCompatibilityIndex, target_type_ref: SemanticTypeRef
) -> frozenset[str]:
    target_type_name = semantic_type_canonical_name(target_type_ref)
    compatible_names = {target_type_name}

    if semantic_type_is_reference(target_type_ref) or semantic_type_is_interface(target_type_ref):
        compatible_names.add(TYPE_NAME_OBJ)

    if target_type_ref.class_id is not None:
        compatible_names.update(compatibility_index.implemented_interfaces_by_class_name.get(target_type_name, ()))

    return frozenset(compatible_names)
