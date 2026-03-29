from __future__ import annotations

from compiler.codegen.asm import stack_slot_operand
from compiler.common.collection_protocols import ArrayRuntimeKind


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

ARRAY_RUNTIME_KIND_TAGS: dict[ArrayRuntimeKind, int] = {
    ArrayRuntimeKind.I64: RT_ARRAY_KIND_I64,
    ArrayRuntimeKind.U64: RT_ARRAY_KIND_U64,
    ArrayRuntimeKind.U8: RT_ARRAY_KIND_U8,
    ArrayRuntimeKind.BOOL: RT_ARRAY_KIND_BOOL,
    ArrayRuntimeKind.DOUBLE: RT_ARRAY_KIND_DOUBLE,
    ArrayRuntimeKind.REF: RT_ARRAY_KIND_REF,
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


def array_runtime_kind_tag(runtime_kind: ArrayRuntimeKind) -> int:
    return ARRAY_RUNTIME_KIND_TAGS[runtime_kind]