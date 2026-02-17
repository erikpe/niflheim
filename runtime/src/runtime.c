#include "runtime.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static RtThreadState g_thread_state = {0};

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
    (void)ts;
    const uint64_t total = (uint64_t)sizeof(RtObjHeader) + payload_bytes;
    RtObjHeader* obj = (RtObjHeader*)calloc(1, (size_t)total);
    if (!obj) {
        rt_panic("out of memory");
    }

    obj->type_id = type ? type->type_id : 0;
    obj->gc_flags = 0;
    obj->size_bytes = total;
    obj->type = type;
    return (void*)obj;
}

void rt_panic(const char* message) {
    fprintf(stderr, "panic: %s\n", message ? message : "unknown");
    abort();
}
