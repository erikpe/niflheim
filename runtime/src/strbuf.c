#include "runtime.h"
#include "str.h"
#include "strbuf.h"

#include <stddef.h>
#include <string.h>

typedef struct RtStrBufStorageObj {
    RtObjHeader header;
    uint64_t capacity;
    uint8_t bytes[];
} RtStrBufStorageObj;

typedef struct RtStrBufObj {
    RtObjHeader header;
    uint64_t len;
    RtStrBufStorageObj* storage;
} RtStrBufObj;

static void rt_strbuf_trace(void* obj, void (*mark_ref)(void** slot));

RtType rt_type_strbuf_desc = {
    .type_id = 0x53424601u,
    .flags = RT_TYPE_FLAG_HAS_REFS,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtStrBufObj),
    .debug_name = "StrBuf",
    .trace_fn = rt_strbuf_trace,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_strbuf_storage = {
    .type_id = 0x53425331u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtStrBufStorageObj),
    .debug_name = "StrBufStorage",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static void rt_strbuf_trace(void* obj, void (*mark_ref)(void** slot)) {
    RtStrBufObj* strbuf = (RtStrBufObj*)obj;
    mark_ref((void**)&strbuf->storage);
}

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

static RtStrBufStorageObj* rt_strbuf_storage_new(uint64_t capacity) {
    RtThreadState* ts = rt_thread_state();
    RtStrBufStorageObj* storage = (RtStrBufStorageObj*)rt_alloc_obj(
        ts,
        &g_rt_type_strbuf_storage,
        offsetof(RtStrBufStorageObj, bytes) + capacity
    );
    storage->capacity = capacity;
    if (capacity > 0) {
        memset(storage->bytes, 0, (size_t)capacity);
    }
    return storage;
}

void rt_strbuf_reserve(void* strbuf_obj, uint64_t new_capacity) {
    RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_reserve: object is not StrBuf");

    RtStrBufStorageObj* storage = strbuf->storage;
    rt_require(storage != NULL, "rt_strbuf_reserve: internal storage is null");

    if (new_capacity <= storage->capacity) {
        return;
    }

    RtThreadState* ts = rt_thread_state();
    RtRootFrame frame;
    void* slots[1] = {NULL};
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(ts, &frame);

    RtStrBufStorageObj* grown = rt_strbuf_storage_new(new_capacity);
    rt_root_slot_store(&frame, 0, grown);

    if (strbuf->len > 0) {
        memcpy(grown->bytes, storage->bytes, (size_t)strbuf->len);
    }
    strbuf->storage = grown;

    rt_pop_roots(ts);
}

void* rt_strbuf_new(uint64_t capacity) {
    RtThreadState* ts = rt_thread_state();
    RtRootFrame frame;
    void* slots[1] = {NULL};
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(ts, &frame);

    RtStrBufStorageObj* storage = rt_strbuf_storage_new(capacity);
    rt_root_slot_store(&frame, 0, storage);

    RtStrBufObj* strbuf = (RtStrBufObj*)rt_alloc_obj(ts, &rt_type_strbuf_desc, sizeof(RtStrBufObj) - sizeof(RtObjHeader));
    strbuf->len = 0;
    strbuf->storage = storage;

    rt_pop_roots(ts);
    return (void*)strbuf;
}

void* rt_strbuf_from_str(const void* str_obj) {
    const uint64_t length = rt_str_len(str_obj);
    RtStrBufObj* strbuf = (RtStrBufObj*)rt_strbuf_new(length);

    RtStrBufStorageObj* storage = strbuf->storage;
    rt_require(storage != NULL, "rt_strbuf_from_str: internal storage is null");

    if (length > 0) {
        const uint8_t* src = rt_str_data_ptr(str_obj);
        memcpy(storage->bytes, src, (size_t)length);
    }
    strbuf->len = length;
    return (void*)strbuf;
}

void* rt_strbuf_to_str(const void* strbuf_obj) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_to_str: object is not StrBuf");
    const RtStrBufStorageObj* storage = strbuf->storage;
    rt_require(storage != NULL, "rt_strbuf_to_str: internal storage is null");
    RtThreadState* ts = rt_thread_state();
    return rt_str_from_bytes(ts, storage->bytes, strbuf->len);
}

uint64_t rt_strbuf_len(const void* strbuf_obj) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_len: object is not StrBuf");
    return strbuf->len;
}

uint8_t rt_strbuf_get_u8(const void* strbuf_obj, uint64_t index) {
    const RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_get_u8: object is not StrBuf");
    const RtStrBufStorageObj* storage = strbuf->storage;
    rt_require(storage != NULL, "rt_strbuf_get_u8: internal storage is null");
    if (index >= strbuf->len) {
        rt_panic("rt_strbuf_get_u8: index out of bounds");
    }
    return storage->bytes[index];
}

void rt_strbuf_set_u8(void* strbuf_obj, uint64_t index, uint8_t value) {
    RtStrBufObj* strbuf = rt_require_strbuf_obj(strbuf_obj, "rt_strbuf_set_u8: object is not StrBuf");
    RtStrBufStorageObj* storage = strbuf->storage;
    rt_require(storage != NULL, "rt_strbuf_set_u8: internal storage is null");
    if (index >= strbuf->len) {
        rt_panic("rt_strbuf_set_u8: index out of bounds");
    }
    storage->bytes[index] = value;
}
