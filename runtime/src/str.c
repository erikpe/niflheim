#include "runtime.h"
#include "str.h"

#include <stddef.h>
#include <stdlib.h>
#include <string.h>

typedef struct RtStrObj {
    RtObjHeader header;
    uint64_t len;
    uint8_t bytes[];
} RtStrObj;

RtType rt_type_str_desc = {
    .type_id = 0x53545201u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtStrObj),
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
    if (str->header.type != &rt_type_str_desc) {
        rt_panic(api_name);
    }
    return str;
}

static void rt_panic_from_bytes(const uint8_t* bytes, uint64_t len, const char* api_name) {
    if (len > (uint64_t)(SIZE_MAX - 1)) {
        rt_panic("rt_panic_*: message too large");
    }

    const size_t message_len = (size_t)len;
    char* message = (char*)malloc(message_len + 1);
    if (message == NULL) {
        rt_panic("rt_panic_*: out of memory");
    }

    if (message_len > 0) {
        memcpy(message, bytes, message_len);
    }
    message[message_len] = '\0';

    (void)api_name;
    rt_panic(message);
}

void* rt_str_from_bytes(RtThreadState* ts, const uint8_t* bytes, uint64_t len) {
    if (len > 0 && bytes == NULL) {
        rt_panic("rt_str_from_bytes: bytes is NULL with non-zero length");
    }

    RtStrObj* str = (RtStrObj*)rt_alloc_obj(ts, &rt_type_str_desc, sizeof(uint64_t) + len);
    str->len = len;
    if (len > 0) {
        memcpy(str->bytes, bytes, (size_t)len);
    }
    return (void*)str;
}

void* rt_str_from_char(uint8_t value) {
    RtThreadState* ts = rt_thread_state();
    return rt_str_from_bytes(ts, &value, 1);
}

uint64_t rt_str_len(const void* str_obj) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_len: object is not Str");
    return str->len;
}

const uint8_t* rt_str_data_ptr(const void* str_obj) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_data_ptr: object is not Str");
    return str->bytes;
}

uint8_t rt_str_get_u8(const void* str_obj, int64_t index) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_get_u8: object is not Str");
    if (index < 0 || index >= (int64_t)str->len) {
        rt_panic("rt_str_get_u8: index out of bounds");
    }
    return str->bytes[index];
}

void* rt_str_slice(const void* str_obj, int64_t begin, int64_t end) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_str_slice: object is not Str");
    if (begin < 0 || end < 0 || begin > end || end > (int64_t)str->len) {
        rt_panic("rt_str_slice: invalid slice range");
    }

    const uint64_t slice_len = end - begin;
    const uint8_t* slice_bytes = str->bytes + begin;
    RtThreadState* ts = rt_thread_state();
    return rt_str_from_bytes(ts, slice_bytes, slice_len);
}

void rt_panic_str(const void* str_obj) {
    const RtStrObj* str = rt_require_str_obj(str_obj, "rt_panic_str: object is not Str");

    rt_panic_from_bytes(str->bytes, str->len, "rt_panic_str");
}

void rt_panic_newstr(const void* newstr_obj) {
    rt_require(newstr_obj != NULL, "rt_panic_newstr: object is null");

    const uint8_t* object_bytes = (const uint8_t*)newstr_obj;
    const void* storage_obj = *(const void* const*)(object_bytes + sizeof(RtObjHeader));
    rt_require(storage_obj != NULL, "rt_panic_newstr: _bytes storage is null");

    const uint64_t len = rt_array_len(storage_obj);
    if (len > (uint64_t)(SIZE_MAX - 1)) {
        rt_panic("rt_panic_newstr: message too large");
    }

    uint8_t* bytes = NULL;
    if (len > 0) {
        bytes = (uint8_t*)malloc((size_t)len);
        if (bytes == NULL) {
            rt_panic("rt_panic_newstr: out of memory");
        }
        for (uint64_t i = 0; i < len; i++) {
            bytes[i] = (uint8_t)rt_array_get_u8(storage_obj, (int64_t)i);
        }
    }

    rt_panic_from_bytes(bytes, len, "rt_panic_newstr");

    if (bytes != NULL) {
        free(bytes);
    }
}
