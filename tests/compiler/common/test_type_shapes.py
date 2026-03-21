import pytest

from compiler.common.type_names import STR_CLASS_NAME, is_str_type_name
from compiler.common.type_shapes import (
    array_element_type_name,
    function_type_return_type_name,
    is_array_type_name,
    is_function_type_name,
    is_reference_type_name,
)


def test_type_shape_helpers_cover_function_and_array_types() -> None:
    assert is_function_type_name("fn(i64,u64)->bool")
    assert function_type_return_type_name("fn(i64,u64)->bool") == "bool"
    assert is_array_type_name("i64[][]")
    assert array_element_type_name("i64[][]") == "i64[]"


def test_type_shape_helpers_classify_reference_types() -> None:
    assert not is_reference_type_name("i64")
    assert not is_reference_type_name("fn(i64)->bool")
    assert is_reference_type_name("Box")
    assert is_reference_type_name("Obj")


def test_str_type_helper_accepts_local_and_qualified_names() -> None:
    assert STR_CLASS_NAME == "Str"
    assert is_str_type_name("Str")
    assert is_str_type_name("std.core::Str")
    assert not is_str_type_name("String")


def test_function_type_return_type_name_rejects_malformed_types() -> None:
    with pytest.raises(ValueError, match="not a function type name"):
        function_type_return_type_name("i64")