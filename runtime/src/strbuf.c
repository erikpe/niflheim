#include "runtime.h"
#include "str.h"
#include "strbuf.h"

#include <stddef.h>

typedef struct RtStrObj {
    RtObjHeader header;
    uint64_t len;
    uint8_t bytes[];
} RtStrObj;

typedef struct RtStrBufObj {
    RtObjHeader header;
    uint64_t len;
    uint8_t bytes[];
} RtStrBufObj;

RtType rt_type_strbuf_desc = {
    .type_id = 0x53424601u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t),
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

static RtStrObj* rt_require_str_obj(const void* str_obj, const char* api_name) {
    extern RtType rt_type_str_desc;

    rt_require(str_obj != NULL, "Str API called with null object");

    RtStrObj* str = (RtStrObj*)str_obj;
    if (str->header.type != &rt_type_str_desc) {
        rt_panic(api_name);
    }
    return str;
}

static RtStrBufObj* rt_require_strbuf_obj(const void* strbuf_obj, const char* api_name) {
    rt_require(strbuf_obj != NULL, "StrBuf API called with null object");

    RtStrBufObj* strbuf = (RtStrBufObj*)strbuf_obj;
    if (strbuf->header.type != &rt_type_strbuf_desc) {
        rt_panic(api_name);
    }
    return strbuf;
}

void* rt_strbuf_new(int64_t len) {
    if (len < 0) {
        rt_panic("rt_strbuf_new: length must be non-negative");
    }

    const uint64_t ulen = (uint64_t)len;
    RtThreadState* ts = rt_thread_state();
    RtStrBufObj* strbuf = (RtStrBufObj*)rt_alloc_obj(ts, &rt_type_strbuf_desc, sizeof(uint64_t) + ulen);
    strbuf->len = ulen;
    if (ulen > 0) {
        for (uint64_t i = 0; i < ulen; i++) {
            strbuf->bytes[i] = 0;
        }
    }
    return (void*)strbuf;
}

void* rt_strbuf_from_str(const void* str_obj) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_strbuf_from_str: object is not Str");
    RtThreadState* ts = rt_thread_state();
    RtStrBufObj* strbuf = (RtStrBufObj*)rt_alloc_obj(ts, &rt_type_strbuf_desc, sizeof(uint64_t) + str->len);
    strbuf->len = str->len;
    for (uint64_t i = 0; i < str->len; i++) {
        strbuf->bytes[i] = str->bytes[i];
    }
    return (void*)strbuf;
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

void* rt_strbuf_to_str(const void* strbuf_obj) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_to_str: object is not StrBuf");
    RtThreadState* ts = rt_thread_state();
    return rt_str_from_bytes(ts, strbuf->bytes, strbuf->len);
}
