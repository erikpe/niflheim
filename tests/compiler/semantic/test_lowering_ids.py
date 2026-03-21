from __future__ import annotations

import pytest

from compiler.semantic.lowering.ids import (
    class_id_from_type_name,
    constructor_id_from_type_name,
    interface_id_for_type_name,
    interface_method_id_for_type_name,
    method_id_for_type_name,
    split_type_name,
)
from compiler.semantic.symbols import ClassId, ConstructorId, InterfaceId, InterfaceMethodId, MethodId


def test_split_type_name_resolves_unqualified_names_against_current_module() -> None:
    assert split_type_name(("main",), "Box") == (("main",), "Box")


def test_split_type_name_resolves_qualified_names_to_declaring_module() -> None:
    assert split_type_name(("main",), "pkg.alpha::Box") == (("pkg", "alpha"), "Box")


def test_split_type_name_requires_module_path_for_unqualified_names() -> None:
    with pytest.raises(ValueError, match="Cannot resolve unqualified type name 'Box' without a module path"):
        split_type_name(None, "Box")


def test_type_name_id_helpers_build_canonical_ids_for_local_types() -> None:
    module_path = ("main",)

    assert class_id_from_type_name(module_path, "Box") == ClassId(module_path=("main",), name="Box")
    assert constructor_id_from_type_name(module_path, "Box") == ConstructorId(module_path=("main",), class_name="Box")
    assert method_id_for_type_name(module_path, "Box", "read") == MethodId(
        module_path=("main",), class_name="Box", name="read"
    )
    assert interface_id_for_type_name(module_path, "Hashable") == InterfaceId(module_path=("main",), name="Hashable")
    assert interface_method_id_for_type_name(module_path, "Hashable", "hash_code") == InterfaceMethodId(
        module_path=("main",), interface_name="Hashable", name="hash_code"
    )


def test_type_name_id_helpers_build_canonical_ids_for_imported_types() -> None:
    current_module = ("main",)

    assert class_id_from_type_name(current_module, "pkg.alpha::Box") == ClassId(
        module_path=("pkg", "alpha"), name="Box"
    )
    assert constructor_id_from_type_name(current_module, "pkg.alpha::Box") == ConstructorId(
        module_path=("pkg", "alpha"), class_name="Box"
    )
    assert method_id_for_type_name(current_module, "pkg.alpha::Box", "read") == MethodId(
        module_path=("pkg", "alpha"), class_name="Box", name="read"
    )
    assert interface_id_for_type_name(current_module, "pkg.alpha::Hashable") == InterfaceId(
        module_path=("pkg", "alpha"), name="Hashable"
    )
    assert interface_method_id_for_type_name(current_module, "pkg.alpha::Hashable", "hash_code") == InterfaceMethodId(
        module_path=("pkg", "alpha"), interface_name="Hashable", name="hash_code"
    )