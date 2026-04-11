#include "runtime.h"
#include "gc_trace.h"

#include <math.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>

enum {
    RT_TRACE_FRAME_INITIAL_CAPACITY = 8,
};

static RtThreadState g_thread_state = {0};

static const char* rt_type_name_or_unknown(const RtType* type) {
    if (type == NULL || type->debug_name == NULL) {
        return "<unknown>";
    }
    return type->debug_name;
}

static __attribute__((noreturn)) void rt_panic_numeric_cast(const char* from_type, const char* to_type) {
    char message[256];
    snprintf(
        message,
        sizeof(message),
        "numeric cast out of range (%s -> %s)",
        from_type ? from_type : "<unknown>",
        to_type ? to_type : "<unknown>"
    );
    rt_panic(message);
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

static void rt_trace_release_stack(void) {
    free(g_thread_state.trace_frames);
    g_thread_state.trace_frames = NULL;
    g_thread_state.trace_size = 0u;
    g_thread_state.trace_capacity = 0u;
}

static void rt_trace_ensure_capacity(uint32_t required) {
    if (required <= g_thread_state.trace_capacity) {
        return;
    }

    uint32_t new_capacity = g_thread_state.trace_capacity;
    if (new_capacity == 0u) {
        new_capacity = RT_TRACE_FRAME_INITIAL_CAPACITY;
    }
    while (new_capacity < required) {
        if (new_capacity > UINT32_MAX / 2u) {
            new_capacity = required;
            break;
        }
        new_capacity *= 2u;
    }

    RtTraceFrame* new_frames = (RtTraceFrame*)realloc(
        g_thread_state.trace_frames,
        (size_t)new_capacity * sizeof(RtTraceFrame)
    );
    if (new_frames == NULL) {
        rt_panic("rt_trace_push: out of memory");
    }

    g_thread_state.trace_frames = new_frames;
    g_thread_state.trace_capacity = new_capacity;
}

void rt_init(void) {
    rt_trace_release_stack();
    g_thread_state.roots_top = NULL;
}

void rt_shutdown(void) {
    rt_gc_trace_print_summary();
    rt_gc_reset_state();
    rt_trace_release_stack();
}

RtThreadState* rt_thread_state(void) {
    return &g_thread_state;
}

void rt_trace_push(const char* function_name, const char* file_path, uint32_t line, uint32_t column) {
    if (g_thread_state.trace_size >= g_thread_state.trace_capacity) {
        rt_trace_ensure_capacity(g_thread_state.trace_size + 1u);
    }

    RtTraceFrame* frame = &g_thread_state.trace_frames[g_thread_state.trace_size];
    frame->function_name = function_name;
    frame->file_path = file_path;
    frame->line = line;
    frame->column = column;
    g_thread_state.trace_size += 1u;
}

void rt_trace_pop(void) {
    if (g_thread_state.trace_size == 0u) {
        rt_panic("rt_trace_pop: trace stack underflow");
    }

    g_thread_state.trace_size -= 1u;
}

void rt_trace_set_location(uint32_t line, uint32_t column) {
    if (g_thread_state.trace_size == 0u) {
        return;
    }

    RtTraceFrame* top = &g_thread_state.trace_frames[g_thread_state.trace_size - 1u];
    top->line = line;
    top->column = column;
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


static uint64_t rt_type_is_instance_of(const RtType* concrete_type, const RtType* expected_type) {
    if (expected_type == NULL) {
        rt_panic("rt_type_is_instance_of called with NULL expected_type");
    }

    for (const RtType* current_type = concrete_type; current_type != NULL; current_type = current_type->super_type) {
        if (current_type == expected_type) {
            return 1u;
        }
    }

    return 0u;
}

static uint64_t rt_obj_has_type(void* obj, const RtType* expected_type) {
    if (obj == NULL) {
        return 0u;
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    return rt_type_is_instance_of(header->type, expected_type);
}

void* rt_checked_cast(void* obj, const RtType* expected_type) {
    if (obj == NULL) {
        return NULL;
    }
    if (rt_obj_has_type(obj, expected_type) != 0u) {
        return obj;
    }

    RtObjHeader* header = (RtObjHeader*)obj;

    rt_panic_bad_cast(
        rt_type_name_or_unknown(header->type),
        rt_type_name_or_unknown(expected_type)
    );
}

uint64_t rt_is_instance_of_type(void* obj, const RtType* expected_type) {
    return rt_obj_has_type(obj, expected_type);
}

uint64_t rt_obj_same_type(void* lhs, void* rhs) {
    if (lhs == NULL || rhs == NULL) {
        return 0u;
    }

    RtObjHeader* lhs_header = (RtObjHeader*)lhs;
    RtObjHeader* rhs_header = (RtObjHeader*)rhs;
    return lhs_header->type == rhs_header->type ? 1u : 0u;
}

double rt_cast_u64_to_double(uint64_t value) {
    return (double)value;
}

int64_t rt_cast_double_to_i64(double value) {
    if (!isfinite(value)) {
        rt_panic_numeric_cast("double", "i64");
    }

    if (value < -9223372036854775808.0 || value >= 9223372036854775808.0) {
        rt_panic_numeric_cast("double", "i64");
    }
    return (int64_t)value;
}

uint64_t rt_cast_double_to_u64(double value) {
    if (!isfinite(value)) {
        rt_panic_numeric_cast("double", "u64");
    }

    if (value < 0.0 || value >= 18446744073709551616.0) {
        rt_panic_numeric_cast("double", "u64");
    }
    return (uint64_t)value;
}

uint64_t rt_cast_double_to_u8(double value) {
    if (!isfinite(value)) {
        rt_panic_numeric_cast("double", "u8");
    }

    if (value < 0.0 || value >= 256.0) {
        rt_panic_numeric_cast("double", "u8");
    }
    return (uint64_t)value;
}
