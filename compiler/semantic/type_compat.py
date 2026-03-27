from __future__ import annotations

from typing import Literal

from compiler.common.type_names import NON_CLASS_TYPE_NAMES, PRIMITIVE_TYPE_NAMES, TYPE_NAME_NULL
from compiler.common.type_shapes import is_array_type_name, is_function_type_name
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ClassId, InterfaceId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_null_type_ref,
    semantic_primitive_type_ref,
    semantic_type_canonical_name,
    semantic_type_display_name,
)


def compat_semantic_type_ref_from_name(
    current_module_path: ModulePath, type_name: str, *, nominal_kind: Literal["reference", "interface"] = "reference"
) -> SemanticTypeRef:
    """Reconstruct a semantic type from compatibility-era string data.

    Prefer canonical lowering output or checked-type conversion whenever the
    compiler already has resolved type information. This module exists for the
    narrow set of boundaries that still need to interpret legacy type-name
    strings explicitly.
    """
    text = type_name.strip()
    if is_function_type_name(text):
        params_text, return_text = _split_function_type(text)
        param_types = tuple(
            compat_semantic_type_ref_from_name(current_module_path, param_text)
            for param_text in _split_top_level(params_text)
            if param_text
        )
        return_type = compat_semantic_type_ref_from_name(current_module_path, return_text)
        return _callable_semantic_type_ref(param_types, return_type)

    if is_array_type_name(text):
        element_type = compat_semantic_type_ref_from_name(current_module_path, text[:-2], nominal_kind=nominal_kind)
        return _array_semantic_type_ref(element_type)

    if text == TYPE_NAME_NULL:
        return semantic_null_type_ref()

    if text in PRIMITIVE_TYPE_NAMES:
        return semantic_primitive_type_ref(text)

    if nominal_kind == "interface":
        interface_id = _interface_id_from_name(current_module_path, text)
        canonical_name = (
            text if interface_id is None else _qualified_nominal_name(interface_id.module_path, interface_id.name)
        )
        return SemanticTypeRef(
            kind="interface", canonical_name=canonical_name, display_name=text, interface_id=interface_id
        )

    class_id = _class_id_from_name(current_module_path, text)
    canonical_name = text if class_id is None else _qualified_nominal_name(class_id.module_path, class_id.name)
    return SemanticTypeRef(kind="reference", canonical_name=canonical_name, display_name=text, class_id=class_id)


def best_effort_semantic_type_ref_from_name(
    current_module_path: ModulePath, type_name: str, *, nominal_kind: Literal["reference", "interface"] = "reference"
) -> SemanticTypeRef:
    """Backward-compatible test helper for handwritten semantic fixtures."""
    return compat_semantic_type_ref_from_name(current_module_path, type_name, nominal_kind=nominal_kind)


def _callable_semantic_type_ref(
    param_types: tuple[SemanticTypeRef, ...], return_type: SemanticTypeRef
) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="callable",
        canonical_name=f"fn({', '.join(semantic_type_canonical_name(param) for param in param_types)}) -> {semantic_type_canonical_name(return_type)}",
        display_name=f"fn({', '.join(semantic_type_display_name(param) for param in param_types)}) -> {semantic_type_display_name(return_type)}",
        param_types=param_types,
        return_type=return_type,
    )


def _array_semantic_type_ref(element_type: SemanticTypeRef) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="reference",
        canonical_name=f"{semantic_type_canonical_name(element_type)}[]",
        display_name=f"{semantic_type_display_name(element_type)}[]",
        element_type=element_type,
    )


def _class_id_from_name(current_module_path: ModulePath, type_name: str) -> ClassId | None:
    if not _is_user_nominal_type_name(type_name):
        return None
    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return ClassId(module_path=tuple(owner_dotted.split(".")), name=class_name)
    return ClassId(module_path=current_module_path, name=type_name)


def _interface_id_from_name(current_module_path: ModulePath, type_name: str) -> InterfaceId | None:
    if not _is_user_nominal_type_name(type_name):
        return None
    if "::" in type_name:
        owner_dotted, interface_name = type_name.split("::", 1)
        return InterfaceId(module_path=tuple(owner_dotted.split(".")), name=interface_name)
    return InterfaceId(module_path=current_module_path, name=type_name)


def _qualified_nominal_name(module_path: ModulePath, name: str) -> str:
    return f"{'.'.join(module_path)}::{name}"


def _is_user_nominal_type_name(type_name: str) -> bool:
    return bool(type_name) and type_name not in NON_CLASS_TYPE_NAMES and not type_name.startswith("__")


def _split_function_type(type_name: str) -> tuple[str, str]:
    depth = 0
    close_index = -1
    for index, char in enumerate(type_name[2:], start=2):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = index
                break
    if close_index < 0:
        raise ValueError(f"Invalid function type name '{type_name}'")
    suffix = type_name[close_index + 1 :].lstrip()
    if not suffix.startswith("->"):
        raise ValueError(f"Invalid function type name '{type_name}'")
    return type_name[3:close_index], suffix[2:].strip()


def _split_top_level(text: str) -> list[str]:
    if not text:
        return []
    parts: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return parts