from compiler.codegen.types import (
    array_element_runtime_kind,
    array_element_type_name,
    function_type_return_type_name,
)


def test_codegen_type_helpers_cover_function_and_array_type_names() -> None:
    assert function_type_return_type_name("fn(i64,u64)->bool") == "bool"


def test_codegen_array_type_helpers_cover_nested_arrays_and_runtime_kinds() -> None:
    assert array_element_type_name("i64[][]") == "i64[]"
    assert array_element_type_name("i64[]") == "i64"
    assert array_element_runtime_kind("i64") == "i64"
    assert array_element_runtime_kind("double") == "double"
    assert array_element_runtime_kind("Box") == "ref"
