from __future__ import annotations


# These constants mirror runtime/include/runtime.h:RtRootFrame and RtThreadState.
RT_ROOT_FRAME_PREV_OFFSET = 0
RT_ROOT_FRAME_SLOT_COUNT_OFFSET = 8
RT_ROOT_FRAME_RESERVED_OFFSET = 12
RT_ROOT_FRAME_SLOTS_OFFSET = 16
RT_ROOT_FRAME_SIZE_BYTES = 24

RT_THREAD_STATE_ROOTS_TOP_OFFSET = 0


def _field_operand(base_register: str, byte_offset: int, *, width: str) -> str:
    if width not in {"qword", "dword"}:
        raise ValueError(f"unsupported field operand width: {width}")
    if byte_offset == 0:
        return f"{width} ptr [{base_register}]"
    sign = "+" if byte_offset > 0 else "-"
    return f"{width} ptr [{base_register} {sign} {abs(byte_offset)}]"


def thread_state_roots_top_operand(thread_state_register: str) -> str:
    return _field_operand(thread_state_register, RT_THREAD_STATE_ROOTS_TOP_OFFSET, width="qword")


def root_frame_prev_operand(root_frame_register: str) -> str:
    return _field_operand(root_frame_register, RT_ROOT_FRAME_PREV_OFFSET, width="qword")


def root_frame_slot_count_operand(root_frame_register: str) -> str:
    return _field_operand(root_frame_register, RT_ROOT_FRAME_SLOT_COUNT_OFFSET, width="dword")


def root_frame_reserved_operand(root_frame_register: str) -> str:
    return _field_operand(root_frame_register, RT_ROOT_FRAME_RESERVED_OFFSET, width="dword")


def root_frame_slots_operand(root_frame_register: str) -> str:
    return _field_operand(root_frame_register, RT_ROOT_FRAME_SLOTS_OFFSET, width="qword")