from __future__ import annotations

from compiler.codegen.asm import stack_slot_operand
from compiler.common.collection_protocols import ArrayRuntimeKind


ARRAY_API_NULL_PANIC_MESSAGE = "Array API called with null object"


# These constants mirror runtime/src/array.c:RtArrayObj and runtime/include/runtime.h:RtObjHeader.
# RtObjHeader is 24 bytes on the stage-0 ABI: 8-byte type pointer, 8-byte size,
# 4-byte gc_flags, and 4-byte reserved padding.
RT_OBJ_HEADER_SIZE_BYTES = 24
RT_ARRAY_LEN_OFFSET = RT_OBJ_HEADER_SIZE_BYTES
RT_ARRAY_ELEMENT_KIND_OFFSET = RT_ARRAY_LEN_OFFSET + 8
RT_ARRAY_ELEMENT_SIZE_OFFSET = RT_ARRAY_ELEMENT_KIND_OFFSET + 8
RT_ARRAY_DATA_OFFSET = RT_ARRAY_ELEMENT_SIZE_OFFSET + 8

RT_ARRAY_KIND_I64 = 1
RT_ARRAY_KIND_U64 = 2
RT_ARRAY_KIND_U8 = 3
RT_ARRAY_KIND_BOOL = 4
RT_ARRAY_KIND_DOUBLE = 5
RT_ARRAY_KIND_REF = 6

RT_ARRAY_PRIMITIVE_TYPE_SYMBOL = "rt_type_array_primitive_desc"
RT_ARRAY_REFERENCE_TYPE_SYMBOL = "rt_type_array_reference_desc"

ARRAY_RUNTIME_KIND_TAGS: dict[ArrayRuntimeKind, int] = {
    ArrayRuntimeKind.I64: RT_ARRAY_KIND_I64,
    ArrayRuntimeKind.U64: RT_ARRAY_KIND_U64,
    ArrayRuntimeKind.U8: RT_ARRAY_KIND_U8,
    ArrayRuntimeKind.BOOL: RT_ARRAY_KIND_BOOL,
    ArrayRuntimeKind.DOUBLE: RT_ARRAY_KIND_DOUBLE,
    ArrayRuntimeKind.REF: RT_ARRAY_KIND_REF,
}

ARRAY_RUNTIME_KIND_DISPLAY_NAMES: dict[int, str] = {
    RT_ARRAY_KIND_I64: "i64[]",
    RT_ARRAY_KIND_U64: "u64[]",
    RT_ARRAY_KIND_U8: "u8[]",
    RT_ARRAY_KIND_BOOL: "bool[]",
    RT_ARRAY_KIND_DOUBLE: "double[]",
    RT_ARRAY_KIND_REF: "Obj[]",
}

DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES: dict[ArrayRuntimeKind, int] = {
    ArrayRuntimeKind.I64: 8,
    ArrayRuntimeKind.U64: 8,
    ArrayRuntimeKind.U8: 1,
    ArrayRuntimeKind.BOOL: 8,
    ArrayRuntimeKind.DOUBLE: 8,
}


def array_length_operand(array_register: str) -> str:
    return stack_slot_operand(array_register, RT_ARRAY_LEN_OFFSET)


def array_element_kind_operand(array_register: str) -> str:
    return stack_slot_operand(array_register, RT_ARRAY_ELEMENT_KIND_OFFSET)


def array_element_size_operand(array_register: str) -> str:
    return stack_slot_operand(array_register, RT_ARRAY_ELEMENT_SIZE_OFFSET)


def array_data_operand(array_register: str) -> str:
    return stack_slot_operand(array_register, RT_ARRAY_DATA_OFFSET)


def array_data_address(array_register: str) -> str:
    if RT_ARRAY_DATA_OFFSET == 0:
        return f"[{array_register}]"
    return f"[{array_register} + {RT_ARRAY_DATA_OFFSET}]"


def array_data_index_address(array_register: str, index_register: str, *, element_size: int) -> str:
    if element_size not in {1, 8}:
        raise ValueError(f"unsupported direct array element size: {element_size}")
    if element_size == 1:
        return f"[{array_register} + {index_register} + {RT_ARRAY_DATA_OFFSET}]"
    return f"[{array_register} + {index_register} * {element_size} + {RT_ARRAY_DATA_OFFSET}]"


def array_runtime_kind_tag(runtime_kind: ArrayRuntimeKind | str) -> int:
    if isinstance(runtime_kind, ArrayRuntimeKind):
        return ARRAY_RUNTIME_KIND_TAGS[runtime_kind]

    runtime_kind_by_name = {
        "i64": ArrayRuntimeKind.I64,
        "u64": ArrayRuntimeKind.U64,
        "u8": ArrayRuntimeKind.U8,
        "bool": ArrayRuntimeKind.BOOL,
        "double": ArrayRuntimeKind.DOUBLE,
        "ref": ArrayRuntimeKind.REF,
    }
    resolved_runtime_kind = runtime_kind_by_name.get(runtime_kind)
    if resolved_runtime_kind is None:
        raise ValueError(f"unsupported array runtime kind: {runtime_kind}")
    return ARRAY_RUNTIME_KIND_TAGS[resolved_runtime_kind]


def array_runtime_kind_display_name_for_tag(kind_tag: int) -> str:
    return ARRAY_RUNTIME_KIND_DISPLAY_NAMES.get(kind_tag, "<unknown-array-kind>")


def is_direct_primitive_array_runtime_kind(runtime_kind: ArrayRuntimeKind | None) -> bool:
    return runtime_kind in DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES


def direct_primitive_array_element_size(runtime_kind: ArrayRuntimeKind) -> int:
    element_size = DIRECT_PRIMITIVE_ARRAY_ELEMENT_SIZES.get(runtime_kind)
    if element_size is None:
        raise ValueError(f"unsupported direct primitive array runtime kind: {runtime_kind}")
    return element_size


def direct_primitive_array_data_index_address(
    array_register: str, index_register: str, *, runtime_kind: ArrayRuntimeKind
) -> str:
    return array_data_index_address(
        array_register,
        index_register,
        element_size=direct_primitive_array_element_size(runtime_kind),
    )


def direct_primitive_array_store_operand(
    array_register: str, index_register: str, *, runtime_kind: ArrayRuntimeKind
) -> str:
    address = direct_primitive_array_data_index_address(
        array_register,
        index_register,
        runtime_kind=runtime_kind,
    )
    if runtime_kind is ArrayRuntimeKind.U8:
        return f"byte ptr {address}"
    return f"qword ptr {address}"


def direct_ref_array_store_operand(array_register: str, index_register: str) -> str:
    return f"qword ptr {array_data_index_address(array_register, index_register, element_size=8)}"


def emit_direct_ref_array_element_store(codegen, *, array_register: str, index_register: str, value_register: str) -> None:
    # This is the only legal compiler-emitted fast-path mutation site for ref[] writes.
    # If the collector later needs write barriers or remembered-set updates, they belong here.
    codegen.asm.instr(f"mov {direct_ref_array_store_operand(array_register, index_register)}, {value_register}")