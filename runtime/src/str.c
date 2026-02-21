#include "runtime.h"
#include "str.h"

#include <stddef.h>
#include <string.h>

typedef struct RtStrObj {
    RtObjHeader header;
    uint64_t len;
    uint8_t bytes[];
} RtStrObj;

static RtType g_rt_type_str = {
    .type_id = 0x53545201u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t),
    .debug_name = "Str",
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
    rt_require(str_obj != NULL, "Str API called with null object");

    RtStrObj* str = (RtStrObj*)str_obj;
    if (str->header.type != &g_rt_type_str) {
        rt_panic(api_name);
    }
    return str;
}

void* rt_str_from_bytes(RtThreadState* ts, const uint8_t* bytes, uint64_t len) {
    if (len > 0 && bytes == NULL) {
        rt_panic("rt_str_from_bytes: bytes is NULL with non-zero length");
    }

    RtStrObj* str = (RtStrObj*)rt_alloc_obj(ts, &g_rt_type_str, sizeof(uint64_t) + len);
    str->len = len;
    if (len > 0) {
        memcpy(str->bytes, bytes, (size_t)len);
    }
    return (void*)str;
}

uint64_t rt_str_len(const void* str_obj) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_len: object is not Str");
    return str->len;
}

uint64_t rt_str_get_u8(const void* str_obj, uint64_t index) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_get_u8: object is not Str");
    if (index >= str->len) {
        rt_panic("rt_str_get_u8: index out of bounds");
    }
    return (uint64_t)str->bytes[index];
}
