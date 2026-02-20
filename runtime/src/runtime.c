#include "runtime.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

static RtThreadState g_thread_state = {0};

static const char* rt_type_name_or_unknown(const RtType* type) {
    if (type == NULL || type->debug_name == NULL) {
        return "<unknown>";
    }
    return type->debug_name;
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
}

RtThreadState* rt_thread_state(void) {
    return &g_thread_state;
}

void rt_push_roots(RtThreadState* ts, RtRootFrame* frame) {
    frame->prev = ts->roots_top;
    ts->roots_top = frame;
}

void rt_pop_roots(RtThreadState* ts) {
    if (ts->roots_top != NULL) {
        ts->roots_top = ts->roots_top->prev;
    }
}

void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes) {
    if (ts == NULL) {
        ts = rt_thread_state();
    }

    if (type == NULL) {
        rt_panic("rt_alloc_obj called with NULL type metadata");
    }

    const uint64_t total = rt_checked_total_size(payload_bytes);
    RtObjHeader* obj = rt_try_alloc_zeroed(ts, total);
    if (!obj) {
        rt_panic_oom();
    }

    obj->type = type;
    obj->size_bytes = total;
    obj->gc_flags = 0;
    obj->reserved0 = 0;
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
