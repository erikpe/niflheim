from __future__ import annotations

from typing import TYPE_CHECKING

from compiler.common.type_names import PRIMITIVE_TYPE_NAMES, TYPE_NAME_UNIT

if TYPE_CHECKING:
    from compiler.semantic.types import SemanticTypeRef


def is_reference_type_ref(type_ref: SemanticTypeRef) -> bool:
    from compiler.semantic.types import semantic_type_is_array, semantic_type_is_interface, semantic_type_is_reference

    return semantic_type_is_reference(type_ref) or semantic_type_is_interface(type_ref) or semantic_type_is_array(type_ref)


def array_element_runtime_kind(element_type_name: str) -> str:
    if element_type_name in PRIMITIVE_TYPE_NAMES - {TYPE_NAME_UNIT}:
        return element_type_name
    return "ref"


def array_element_runtime_kind_for_type_ref(type_ref: SemanticTypeRef) -> str:
    from compiler.semantic.types import semantic_type_canonical_name

    return array_element_runtime_kind(semantic_type_canonical_name(type_ref))
