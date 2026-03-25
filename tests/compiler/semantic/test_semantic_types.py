from __future__ import annotations

from compiler.semantic.symbols import ClassId
from compiler.semantic.types import (
    semantic_type_canonical_name,
    semantic_type_display_name,
    semantic_type_ref_from_type_info,
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