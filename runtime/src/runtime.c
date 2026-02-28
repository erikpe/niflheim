#include "runtime.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

static RtThreadState g_thread_state = {0};

void rt_gc_maybe_collect(RtThreadState* ts, uint64_t upcoming_bytes);
void rt_gc_track_allocation(RtObjHeader* obj);
void rt_gc_reset_state(void);

static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static void rt_print_stacktrace(void) {
    const RtTraceFrame* frame = g_thread_state.trace_top;
    if (frame == NULL) {
        return;
    }

    fprintf(stderr, "stacktrace:\n");
    while (frame != NULL) {
        const char* function_name = frame->function_name ? frame->function_name : "<unknown>";
        const char* file_path = frame->file_path ? frame->file_path : "<unknown>";
        fprintf(stderr, "  at %s (%s:%u:%u)\n", function_name, file_path, frame->line, frame->column);
        frame = frame->prev;
    }
}

static __attribute__((noreturn)) void rt_abort_with_message(const char* message) {
    fprintf(stderr, "panic: %s\n", message ? message : "unknown");
    if (g_thread_state.trace_top != NULL) {
        const RtTraceFrame* top = g_thread_state.trace_top;
        const char* file_path = top->file_path ? top->file_path : "<unknown>";
        fprintf(stderr, "location: %s:%u:%u\n", file_path, top->line, top->column);
    }
    rt_print_stacktrace();
    abort();
}

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
    g_thread_state.trace_top = NULL;
}

void rt_shutdown(void) {
    rt_gc_reset_state();
}

RtThreadState* rt_thread_state(void) {
    return &g_thread_state;
}

void rt_trace_push(const char* function_name, const char* file_path, uint32_t line, uint32_t column) {
    RtTraceFrame* frame = (RtTraceFrame*)calloc(1, sizeof(RtTraceFrame));
    if (frame == NULL) {
        rt_abort_with_message("rt_trace_push: out of memory");
    }

    frame->function_name = function_name;
    frame->file_path = file_path;
    frame->line = line;
    frame->column = column;
    frame->prev = g_thread_state.trace_top;
    g_thread_state.trace_top = frame;
}

void rt_trace_pop(void) {
    if (g_thread_state.trace_top == NULL) {
        rt_abort_with_message("rt_trace_pop: trace stack underflow");
    }

    RtTraceFrame* top = g_thread_state.trace_top;
    g_thread_state.trace_top = top->prev;
    free(top);
}

void rt_trace_set_location(uint32_t line, uint32_t column) {
    if (g_thread_state.trace_top == NULL) {
        return;
    }

    g_thread_state.trace_top->line = line;
    g_thread_state.trace_top->column = column;
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

void rt_panic(const char* message) {
    rt_abort_with_message(message);
}

void rt_panic_null_deref(void) {
    rt_panic("null dereference");
}

void rt_panic_bad_cast(const char* from_type, const char* to_type) {
    char message[256];
    snprintf(
        message,
        sizeof(message),
        "bad cast (%s -> %s)",
        from_type ? from_type : "<unknown>",
        to_type ? to_type : "<unknown>"
    );
    rt_abort_with_message(message);
}

void rt_panic_null_term_array(const void* array_obj) {
    rt_require(array_obj != NULL, "rt_panic_null_term_array: object is null");

    const char* message = (const char*)rt_array_data_ptr(array_obj);
    rt_require(message != NULL, "rt_panic_null_term_array: array data pointer is null");
    rt_panic(message);
}

void rt_panic_oom(void) {
    rt_panic("out of memory");
}
