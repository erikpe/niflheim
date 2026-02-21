#include "runtime.h"

#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static RtThreadState g_thread_state = {0};

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

void rt_gc_maybe_collect(RtThreadState* ts, uint64_t upcoming_bytes);
void rt_gc_track_allocation(RtObjHeader* obj);
void rt_gc_reset_state(void);

static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static const char* rt_type_name_or_unknown(const RtType* type) {
    if (type == NULL || type->debug_name == NULL) {
        return "<unknown>";
    }
    return type->debug_name;
}

static RtStrObj* rt_require_str_obj(const void* str_obj, const char* api_name) {
    rt_require(str_obj != NULL, "Str API called with null object");

    RtStrObj* str = (RtStrObj*)str_obj;
    if (str->header.type != &g_rt_type_str) {
        rt_panic(api_name);
    }
    return str;
}

static uint64_t rt_checked_total_size(uint64_t payload_bytes) {
    const uint64_t header_bytes = (uint64_t)sizeof(RtObjHeader);
    if (payload_bytes > UINT64_MAX - header_bytes) {
        rt_panic_oom();
    }
    return header_bytes + payload_bytes;
}

static RtObjHeader* rt_try_alloc_zeroed(RtThreadState* ts, uint64_t total_bytes) {
    RtObjHeader* obj = (RtObjHeader*)calloc(1, (size_t)total_bytes);
    if (obj != NULL) {
        return obj;
    }

    rt_gc_collect(ts);
    return (RtObjHeader*)calloc(1, (size_t)total_bytes);
}

void rt_init(void) {
    g_thread_state.roots_top = NULL;
}

void rt_shutdown(void) {
    rt_gc_reset_state();
}

RtThreadState* rt_thread_state(void) {
    return &g_thread_state;
}

void rt_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count) {
    rt_require(frame != NULL, "rt_root_frame_init: frame is NULL");
    rt_require(slot_count == 0 || slots != NULL, "rt_root_frame_init: slots is NULL with non-zero slot_count");

    frame->prev = NULL;
    frame->slot_count = slot_count;
    frame->reserved = 0;
    frame->slots = slots;

    for (uint32_t i = 0; i < slot_count; i++) {
        frame->slots[i] = NULL;
    }
}

void rt_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref) {
    rt_require(frame != NULL, "rt_root_slot_store: frame is NULL");
    rt_require(slot_index < frame->slot_count, "rt_root_slot_store: slot index out of bounds");
    frame->slots[slot_index] = ref;
}

void* rt_root_slot_load(const RtRootFrame* frame, uint32_t slot_index) {
    rt_require(frame != NULL, "rt_root_slot_load: frame is NULL");
    rt_require(slot_index < frame->slot_count, "rt_root_slot_load: slot index out of bounds");
    return frame->slots[slot_index];
}

void rt_push_roots(RtThreadState* ts, RtRootFrame* frame) {
    rt_require(ts != NULL, "rt_push_roots: thread state is NULL");
    rt_require(frame != NULL, "rt_push_roots: frame is NULL");
    rt_require(frame->slot_count == 0 || frame->slots != NULL, "rt_push_roots: frame slots is NULL");

    frame->prev = ts->roots_top;
    ts->roots_top = frame;
}

void rt_pop_roots(RtThreadState* ts) {
    rt_require(ts != NULL, "rt_pop_roots: thread state is NULL");
    rt_require(ts->roots_top != NULL, "rt_pop_roots: shadow stack underflow");

    RtRootFrame* top = ts->roots_top;
    ts->roots_top = top->prev;
    top->prev = NULL;
}

void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes) {
    if (ts == NULL) {
        ts = rt_thread_state();
    }

    if (type == NULL) {
        rt_panic("rt_alloc_obj called with NULL type metadata");
    }

    const uint64_t total = rt_checked_total_size(payload_bytes);
    rt_gc_maybe_collect(ts, total);

    RtObjHeader* obj = rt_try_alloc_zeroed(ts, total);
    if (!obj) {
        rt_panic_oom();
    }

    obj->type = type;
    obj->size_bytes = total;
    obj->gc_flags = 0;
    obj->reserved0 = 0;
    rt_gc_track_allocation(obj);
    return (void*)obj;
}

void* rt_checked_cast(void* obj, const RtType* expected_type) {
    if (obj == NULL) {
        return NULL;
    }
    if (expected_type == NULL) {
        rt_panic("rt_checked_cast called with NULL expected_type");
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    if (header->type == expected_type) {
        return obj;
    }

    rt_panic_bad_cast(
        rt_type_name_or_unknown(header->type),
        rt_type_name_or_unknown(expected_type)
    );
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

void rt_println_i64(int64_t value) {
    printf("%" PRId64 "\n", value);
}

void rt_println_u64(uint64_t value) {
    printf("%" PRIu64 "\n", value);
}

void rt_println_u8(uint64_t value) {
    const uint8_t narrowed = (uint8_t)value;
    printf("%" PRIu8 "\n", narrowed);
}

void rt_println_bool(int64_t value) {
    printf("%s\n", value != 0 ? "true" : "false");
}

void rt_panic(const char* message) {
    fprintf(stderr, "panic: %s\n", message ? message : "unknown");
    abort();
}

void rt_panic_null_deref(void) {
    rt_panic("null dereference");
}

void rt_panic_bad_cast(const char* from_type, const char* to_type) {
    fprintf(
        stderr,
        "panic: bad cast (%s -> %s)\n",
        from_type ? from_type : "<unknown>",
        to_type ? to_type : "<unknown>"
    );
    abort();
}

void rt_panic_oom(void) {
    rt_panic("out of memory");
}
