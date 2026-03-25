from compiler.codegen.types import array_element_runtime_kind, array_element_runtime_kind_for_type_ref, double_value_bits
from compiler.semantic.types import best_effort_semantic_type_ref_from_name


def test_codegen_double_value_bits_is_stable_for_zero() -> None:
    assert double_value_bits(0.0) == 0x0000000000000000


def test_codegen_array_runtime_kind_helper_maps_reference_types_to_ref() -> None:
    assert array_element_runtime_kind("i64") == "i64"
    assert array_element_runtime_kind("double") == "double"
    assert array_element_runtime_kind("Box") == "ref"


def test_codegen_array_runtime_kind_helper_accepts_canonical_type_refs() -> None:
    assert array_element_runtime_kind_for_type_ref(best_effort_semantic_type_ref_from_name(("main",), "i64")) == "i64"
    assert array_element_runtime_kind_for_type_ref(best_effort_semantic_type_ref_from_name(("main",), "Box")) == "ref"
