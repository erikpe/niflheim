from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from compiler.common.type_names import PRIMITIVE_TYPE_NAMES, TYPE_NAME_UNIT
from compiler.common.type_shapes import (
    array_element_type_name as common_array_element_type_name,
    function_type_return_type_name as common_function_type_return_type_name,
    is_array_type_name as common_is_array_type_name,
    is_function_type_name as common_is_function_type_name,
    is_reference_type_name as common_is_reference_type_name,
)

if TYPE_CHECKING:
    from compiler.semantic.types import SemanticTypeRef


def _span_location(span: object | None) -> str | None:
    if span is None:
        return None
    start = getattr(span, "start", None)
    if start is None:
        return None
    path = getattr(start, "path", None)
    line = getattr(start, "line", None)
    column = getattr(start, "column", None)
    if isinstance(path, str) and isinstance(line, int) and isinstance(column, int):
        return f"{path}:{line}:{column}"
    return None


def raise_codegen_error(message: str, *, span: object | None = None) -> None:
    location = _span_location(span)
    if location is not None:
        raise NotImplementedError(f"{message} at {location}")
    raise NotImplementedError(message)


def is_reference_type_name(type_name: str) -> bool:
    return common_is_reference_type_name(type_name)


def is_reference_type_ref(type_ref: SemanticTypeRef) -> bool:
    from compiler.semantic.types import semantic_type_is_array, semantic_type_is_interface, semantic_type_is_reference

    return semantic_type_is_reference(type_ref) or semantic_type_is_interface(type_ref) or semantic_type_is_array(type_ref)


def is_function_type_name(type_name: str) -> bool:
    return common_is_function_type_name(type_name)


def function_type_return_type_name(type_name: str, *, span: object | None = None) -> str:
    try:
        return common_function_type_return_type_name(type_name)
    except ValueError as exc:
        raise_codegen_error(str(exc), span=span)


def is_array_type_name(type_name: str) -> bool:
    return common_is_array_type_name(type_name)


def array_element_type_name(array_type_name: str, *, span: object | None = None) -> str:
    try:
        return common_array_element_type_name(array_type_name)
    except ValueError as exc:
        raise_codegen_error(str(exc), span=span)


def array_element_runtime_kind(element_type_name: str) -> str:
    if element_type_name in PRIMITIVE_TYPE_NAMES - {TYPE_NAME_UNIT}:
        return element_type_name
    return "ref"


def array_element_runtime_kind_for_type_ref(type_ref: SemanticTypeRef) -> str:
    from compiler.semantic.types import semantic_type_canonical_name

    return array_element_runtime_kind(semantic_type_canonical_name(type_ref))


def double_value_bits(value: float) -> int:
    packed = struct.pack("<d", value)
    return struct.unpack("<Q", packed)[0]
