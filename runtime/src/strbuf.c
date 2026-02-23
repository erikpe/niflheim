#include "runtime.h"
#include "str.h"
#include "strbuf.h"

#include <stddef.h>

typedef struct RtStrBufObj {
    RtObjHeader header;
    uint64_t len;
    uint64_t capacity;
    uint8_t bytes[];
} RtStrBufObj;

RtType rt_type_strbuf_desc = {
    .type_id = 0x53424601u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t) + sizeof(uint64_t),
    .debug_name = "StrBuf",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static RtStrBufObj* rt_require_strbuf_obj(const void* strbuf_obj, const char* api_name) {
    rt_require(strbuf_obj != NULL, "StrBuf API called with null object");

    RtStrBufObj* strbuf = (RtStrBufObj*)strbuf_obj;
    if (strbuf->header.type != &rt_type_strbuf_desc) {
        rt_panic(api_name);
    }
    return strbuf;
}

void* rt_strbuf_new(int64_t capacity) {
    if (capacity < 0) {
        rt_panic("rt_strbuf_new: capacity must be non-negative");
    }

    const uint64_t ucapacity = (uint64_t)capacity;
    RtThreadState* ts = rt_thread_state();
    RtStrBufObj* strbuf = (RtStrBufObj*)rt_alloc_obj(ts, &rt_type_strbuf_desc, sizeof(uint64_t) + sizeof(uint64_t) + ucapacity);
    strbuf->len = 0;
    strbuf->capacity = ucapacity;
    if (ucapacity > 0) {
        for (uint64_t i = 0; i < ucapacity; i++) {
            strbuf->bytes[i] = 0;
        }
    }
    return (void*)strbuf;
}

void* rt_strbuf_from_str(const void* str_obj) {
    const uint64_t len = rt_str_len(str_obj);
    RtThreadState* ts = rt_thread_state();
    RtStrBufObj* strbuf = (RtStrBufObj*)rt_alloc_obj(ts, &rt_type_strbuf_desc, sizeof(uint64_t) + sizeof(uint64_t) + len);
    strbuf->len = len;
    strbuf->capacity = len;
    for (uint64_t i = 0; i < len; i++) {
        strbuf->bytes[i] = (uint8_t)rt_str_get_u8(str_obj, i);
    }
    return (void*)strbuf;
}

void* rt_strbuf_to_str(const void* strbuf_obj) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_to_str: object is not StrBuf");
    RtThreadState* ts = rt_thread_state();
    return rt_str_from_bytes(ts, strbuf->bytes, strbuf->len);
}

uint64_t rt_strbuf_len(const void* strbuf_obj) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_len: object is not StrBuf");
    return strbuf->len;
}

uint64_t rt_strbuf_get_u8(const void* strbuf_obj, int64_t index) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_get_u8: object is not StrBuf");
    if (index < 0 || (uint64_t)index >= strbuf->len) {
        rt_panic("rt_strbuf_get_u8: index out of bounds");
    }
    return (uint64_t)strbuf->bytes[(uint64_t)index];
}

void rt_strbuf_set_u8(void* strbuf_obj, int64_t index, uint64_t value) {
    RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_set_u8: object is not StrBuf");
    if (index < 0 || (uint64_t)index >= strbuf->len) {
        rt_panic("rt_strbuf_set_u8: index out of bounds");
    }
    if (value > 255u) {
        rt_panic("rt_strbuf_set_u8: value out of range");
    }
    strbuf->bytes[(uint64_t)index] = (uint8_t)value;
}
