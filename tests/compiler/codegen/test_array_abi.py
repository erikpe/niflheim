from compiler.codegen.abi.array import (
    ARRAY_RUNTIME_KIND_TAGS,
    RT_ARRAY_DATA_OFFSET,
    RT_ARRAY_ELEMENT_KIND_OFFSET,
    RT_ARRAY_ELEMENT_SIZE_OFFSET,
    RT_ARRAY_KIND_BOOL,
    RT_ARRAY_KIND_DOUBLE,
    RT_ARRAY_KIND_I64,
    RT_ARRAY_KIND_REF,
    RT_ARRAY_KIND_U8,
    RT_ARRAY_KIND_U64,
    RT_ARRAY_LEN_OFFSET,
    RT_OBJ_HEADER_SIZE_BYTES,
    array_data_address,
    array_data_index_address,
    array_data_operand,
    array_element_kind_operand,
    array_element_size_operand,
    array_length_operand,
    array_runtime_kind_tag,
)
from compiler.common.collection_protocols import ArrayRuntimeKind


def test_array_abi_offsets_match_runtime_layout() -> None:
    assert RT_OBJ_HEADER_SIZE_BYTES == 24
    assert RT_ARRAY_LEN_OFFSET == 24
    assert RT_ARRAY_ELEMENT_KIND_OFFSET == 32
    assert RT_ARRAY_ELEMENT_SIZE_OFFSET == 40
    assert RT_ARRAY_DATA_OFFSET == 48


def test_array_abi_runtime_kind_tags_match_runtime_enum_values() -> None:
    assert ARRAY_RUNTIME_KIND_TAGS == {
        ArrayRuntimeKind.I64: RT_ARRAY_KIND_I64,
        ArrayRuntimeKind.U64: RT_ARRAY_KIND_U64,
        ArrayRuntimeKind.U8: RT_ARRAY_KIND_U8,
        ArrayRuntimeKind.BOOL: RT_ARRAY_KIND_BOOL,
        ArrayRuntimeKind.DOUBLE: RT_ARRAY_KIND_DOUBLE,
        ArrayRuntimeKind.REF: RT_ARRAY_KIND_REF,
    }
    assert array_runtime_kind_tag(ArrayRuntimeKind.I64) == 1
    assert array_runtime_kind_tag(ArrayRuntimeKind.REF) == 6


def test_array_abi_operand_helpers_format_expected_memory_operands() -> None:
    assert array_length_operand("rax") == "qword ptr [rax + 24]"
    assert array_element_kind_operand("rax") == "qword ptr [rax + 32]"
    assert array_element_size_operand("rax") == "qword ptr [rax + 40]"
    assert array_data_operand("rax") == "qword ptr [rax + 48]"


def test_array_abi_address_helpers_format_data_addresses() -> None:
    assert array_data_address("rax") == "[rax + 48]"
    assert array_data_index_address("rax", "rcx", element_size=1) == "[rax + rcx + 48]"
    assert array_data_index_address("rax", "rcx", element_size=8) == "[rax + rcx * 8 + 48]"


def test_array_abi_rejects_unsupported_direct_element_sizes() -> None:
    try:
        array_data_index_address("rax", "rcx", element_size=4)
    except ValueError as exc:
        assert "unsupported direct array element size" in str(exc)
    else:
        assert False, "expected unsupported element size to be rejected"
