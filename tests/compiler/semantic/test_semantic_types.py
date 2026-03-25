from __future__ import annotations

from compiler.semantic.symbols import ClassId
from compiler.semantic.types import (
    compat_semantic_type_ref_from_name,
    semantic_type_canonical_name,
    semantic_type_callable_params,
    semantic_type_callable_return,
    semantic_type_display_name,
    semantic_type_is_array,
    semantic_type_is_callable,
    semantic_type_is_interface,
    semantic_type_is_null,
    semantic_type_is_primitive,
    semantic_type_is_reference,
    semantic_type_kind,
    semantic_type_nominal_id,
    semantic_type_ref_from_type_info,
    semantic_type_array_element,
    semantic_types_have_same_nominal_identity,
)
from compiler.typecheck.model import TypeInfo


def test_semantic_type_ref_equality_uses_canonical_nominal_identity() -> None:
    local_box = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Box", kind="reference"))
    qualified_box = semantic_type_ref_from_type_info(("other",), TypeInfo(name="main::Box", kind="reference"))

    assert local_box == qualified_box
    assert local_box.class_id == ClassId(module_path=("main",), name="Box")
    assert semantic_type_display_name(local_box) == "Box"
    assert semantic_type_canonical_name(local_box) == "main::Box"


def test_semantic_type_ref_renders_callable_shapes_without_special_callable_names() -> None:
    local_box = TypeInfo(name="Box", kind="reference")
    callable_type = TypeInfo(
        name="__fn__:make_box_array",
        kind="callable",
        callable_params=[local_box, TypeInfo(name="i64", kind="primitive")],
        callable_return=TypeInfo(name="Box[]", kind="reference", element_type=local_box),
    )

    semantic_type = semantic_type_ref_from_type_info(("main",), callable_type)

    assert semantic_type_display_name(semantic_type) == "fn(Box, i64) -> Box[]"
    assert semantic_type_canonical_name(semantic_type) == "fn(main::Box, i64) -> main::Box[]"


def test_semantic_type_helpers_classify_shapes_and_expose_structure() -> None:
    primitive_type = semantic_type_ref_from_type_info(("main",), TypeInfo(name="i64", kind="primitive"))
    null_type = semantic_type_ref_from_type_info(("main",), TypeInfo(name="null", kind="null"))
    interface_type = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Hashable", kind="interface"))
    reference_type = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Box", kind="reference"))
    array_type = semantic_type_ref_from_type_info(
        ("main",), TypeInfo(name="Box[]", kind="reference", element_type=TypeInfo(name="Box", kind="reference"))
    )
    callable_type = semantic_type_ref_from_type_info(
        ("main",),
        TypeInfo(
            name="__fn__:f",
            kind="callable",
            callable_params=[TypeInfo(name="Box", kind="reference")],
            callable_return=TypeInfo(name="bool", kind="primitive"),
        ),
    )

    assert semantic_type_kind(primitive_type) == "primitive"
    assert semantic_type_is_primitive(primitive_type)
    assert semantic_type_is_null(null_type)
    assert semantic_type_is_interface(interface_type)
    assert semantic_type_is_reference(reference_type)
    assert semantic_type_is_array(array_type)
    assert semantic_type_is_callable(callable_type)

    assert semantic_type_array_element(array_type) == reference_type
    assert semantic_type_callable_params(callable_type) == (reference_type,)
    assert semantic_type_callable_return(callable_type).canonical_name == "bool"


def test_semantic_type_nominal_identity_helpers_use_canonical_ids() -> None:
    local_box = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Box", kind="reference"))
    qualified_box = semantic_type_ref_from_type_info(("other",), TypeInfo(name="main::Box", kind="reference"))
    hashable_type = semantic_type_ref_from_type_info(("main",), TypeInfo(name="Hashable", kind="interface"))

    assert semantic_type_nominal_id(local_box) == ClassId(module_path=("main",), name="Box")
    assert semantic_types_have_same_nominal_identity(local_box, qualified_box)
    assert semantic_types_have_same_nominal_identity(local_box, hashable_type) is False


def test_compat_semantic_type_ref_from_name_reconstructs_arrays_and_callables() -> None:
    semantic_type = compat_semantic_type_ref_from_name(("main",), "fn(Box, i64) -> Box[]")

    assert semantic_type_is_callable(semantic_type)
    assert [param.canonical_name for param in semantic_type_callable_params(semantic_type)] == ["main::Box", "i64"]

    return_type = semantic_type_callable_return(semantic_type)
    assert semantic_type_is_array(return_type)
    assert semantic_type_display_name(return_type) == "Box[]"
    assert semantic_type_canonical_name(semantic_type_array_element(return_type)) == "main::Box"