from __future__ import annotations

import ctypes

import pytest

from compiler.backend.program.runtime_layout import (
    RT_ARRAY_DATA_OFFSET,
    RT_ARRAY_ELEMENT_KIND_OFFSET,
    RT_ARRAY_ELEMENT_SIZE_OFFSET,
    RT_ARRAY_KIND_BOOL,
    RT_ARRAY_KIND_DOUBLE,
    RT_ARRAY_KIND_I64,
    RT_ARRAY_KIND_REF,
    RT_ARRAY_KIND_U64,
    RT_ARRAY_KIND_U8,
    RT_ARRAY_LEN_OFFSET,
    RT_INTERFACE_DEBUG_NAME_OFFSET,
    RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES,
    RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES,
    RT_OBJ_HEADER_SIZE_BYTES,
    RT_OBJ_HEADER_TYPE_OFFSET,
    RT_ROOT_FRAME_PREV_OFFSET,
    RT_ROOT_FRAME_RESERVED_OFFSET,
    RT_ROOT_FRAME_SIZE_BYTES,
    RT_ROOT_FRAME_SLOT_COUNT_OFFSET,
    RT_ROOT_FRAME_SLOTS_OFFSET,
    RT_THREAD_STATE_ROOTS_TOP_OFFSET,
    RT_TYPE_CLASS_VTABLE_OFFSET,
    RT_TYPE_DEBUG_NAME_OFFSET,
    RT_TYPE_FLAG_HAS_REFS,
    RT_TYPE_INTERFACE_TABLES_OFFSET,
    RT_TYPE_POINTER_OFFSETS_OFFSET,
    RT_TYPE_SUPER_TYPE_OFFSET,
    RT_VTABLE_ENTRY_SIZE_BYTES,
    array_runtime_kind_display_name_for_tag,
    array_runtime_kind_tag,
    direct_primitive_array_element_size,
    is_direct_primitive_array_runtime_kind,
)
from compiler.common.collection_protocols import ArrayRuntimeKind


class _RtObjHeader(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_void_p),
        ("size_bytes", ctypes.c_uint64),
        ("gc_flags", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
    ]


class _RtInterfaceType(ctypes.Structure):
    _fields_ = [
        ("debug_name", ctypes.c_void_p),
        ("slot_index", ctypes.c_uint32),
        ("method_count", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
    ]


class _RtType(ctypes.Structure):
    _fields_ = [
        ("type_id", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("abi_version", ctypes.c_uint32),
        ("align_bytes", ctypes.c_uint32),
        ("fixed_size_bytes", ctypes.c_uint64),
        ("debug_name", ctypes.c_void_p),
        ("trace_fn", ctypes.c_void_p),
        ("pointer_offsets", ctypes.POINTER(ctypes.c_uint32)),
        ("pointer_offsets_count", ctypes.c_uint32),
        ("reserved0", ctypes.c_uint32),
        ("super_type", ctypes.c_void_p),
        ("interface_tables", ctypes.c_void_p),
        ("interface_slot_count", ctypes.c_uint32),
        ("reserved1", ctypes.c_uint32),
        ("class_vtable", ctypes.c_void_p),
        ("class_vtable_count", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
    ]


class _RtRootFrame(ctypes.Structure):
    _fields_ = [
        ("prev", ctypes.c_void_p),
        ("slot_count", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
        ("slots", ctypes.c_void_p),
    ]


class _RtThreadState(ctypes.Structure):
    _fields_ = [
        ("roots_top", ctypes.c_void_p),
        ("trace_frames", ctypes.c_void_p),
        ("trace_size", ctypes.c_uint32),
        ("trace_capacity", ctypes.c_uint32),
    ]


class _RtArrayPrefix(ctypes.Structure):
    _fields_ = [
        ("header", _RtObjHeader),
        ("len", ctypes.c_uint64),
        ("element_kind", ctypes.c_uint64),
        ("element_size", ctypes.c_uint64),
    ]


def test_root_frame_and_thread_state_layout_matches_runtime_contract() -> None:
    assert RT_THREAD_STATE_ROOTS_TOP_OFFSET == _RtThreadState.roots_top.offset
    assert RT_ROOT_FRAME_PREV_OFFSET == _RtRootFrame.prev.offset
    assert RT_ROOT_FRAME_SLOT_COUNT_OFFSET == _RtRootFrame.slot_count.offset
    assert RT_ROOT_FRAME_RESERVED_OFFSET == _RtRootFrame.reserved.offset
    assert RT_ROOT_FRAME_SLOTS_OFFSET == _RtRootFrame.slots.offset
    assert RT_ROOT_FRAME_SIZE_BYTES == ctypes.sizeof(_RtRootFrame)


def test_object_and_type_layout_matches_runtime_contract() -> None:
    assert RT_OBJ_HEADER_TYPE_OFFSET == _RtObjHeader.type.offset
    assert RT_OBJ_HEADER_SIZE_BYTES == ctypes.sizeof(_RtObjHeader)
    assert RT_INTERFACE_DEBUG_NAME_OFFSET == _RtInterfaceType.debug_name.offset
    assert RT_TYPE_DEBUG_NAME_OFFSET == _RtType.debug_name.offset
    assert RT_TYPE_POINTER_OFFSETS_OFFSET == _RtType.pointer_offsets.offset
    assert RT_TYPE_SUPER_TYPE_OFFSET == _RtType.super_type.offset
    assert RT_TYPE_INTERFACE_TABLES_OFFSET == _RtType.interface_tables.offset
    assert RT_TYPE_CLASS_VTABLE_OFFSET == _RtType.class_vtable.offset
    assert RT_INTERFACE_TABLE_ENTRY_SIZE_BYTES == ctypes.sizeof(ctypes.c_void_p)
    assert RT_INTERFACE_METHOD_ENTRY_SIZE_BYTES == ctypes.sizeof(ctypes.c_void_p)
    assert RT_VTABLE_ENTRY_SIZE_BYTES == ctypes.sizeof(ctypes.c_void_p)
    assert RT_TYPE_FLAG_HAS_REFS == 1


def test_array_layout_tags_and_direct_element_sizes_match_runtime_contract() -> None:
    assert RT_ARRAY_LEN_OFFSET == _RtArrayPrefix.len.offset
    assert RT_ARRAY_ELEMENT_KIND_OFFSET == _RtArrayPrefix.element_kind.offset
    assert RT_ARRAY_ELEMENT_SIZE_OFFSET == _RtArrayPrefix.element_size.offset
    assert RT_ARRAY_DATA_OFFSET == ctypes.sizeof(_RtArrayPrefix)

    assert array_runtime_kind_tag(ArrayRuntimeKind.I64) == RT_ARRAY_KIND_I64
    assert array_runtime_kind_tag(ArrayRuntimeKind.U64) == RT_ARRAY_KIND_U64
    assert array_runtime_kind_tag(ArrayRuntimeKind.U8) == RT_ARRAY_KIND_U8
    assert array_runtime_kind_tag(ArrayRuntimeKind.BOOL) == RT_ARRAY_KIND_BOOL
    assert array_runtime_kind_tag(ArrayRuntimeKind.DOUBLE) == RT_ARRAY_KIND_DOUBLE
    assert array_runtime_kind_tag(ArrayRuntimeKind.REF) == RT_ARRAY_KIND_REF

    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_I64) == "i64[]"
    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_U64) == "u64[]"
    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_U8) == "u8[]"
    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_BOOL) == "bool[]"
    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_DOUBLE) == "double[]"
    assert array_runtime_kind_display_name_for_tag(RT_ARRAY_KIND_REF) == "Obj[]"
    assert array_runtime_kind_display_name_for_tag(999) == "<unknown-array-kind>"

    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.I64) is True
    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.U64) is True
    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.U8) is True
    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.BOOL) is True
    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.DOUBLE) is True
    assert is_direct_primitive_array_runtime_kind(ArrayRuntimeKind.REF) is False
    assert is_direct_primitive_array_runtime_kind(None) is False

    assert direct_primitive_array_element_size(ArrayRuntimeKind.I64) == 8
    assert direct_primitive_array_element_size(ArrayRuntimeKind.U64) == 8
    assert direct_primitive_array_element_size(ArrayRuntimeKind.U8) == 1
    assert direct_primitive_array_element_size(ArrayRuntimeKind.BOOL) == 8
    assert direct_primitive_array_element_size(ArrayRuntimeKind.DOUBLE) == 8

    with pytest.raises(ValueError, match="unsupported direct primitive array runtime kind"):
        direct_primitive_array_element_size(ArrayRuntimeKind.REF)