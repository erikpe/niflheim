#include "runtime.h"
#include "gc_trace.h"

#include <limits.h>
#include <stdlib.h>

static RtThreadState g_thread_state = {0};

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

static const char* rt_interface_name_or_unknown(const RtInterfaceType* interface_type) {
    if (interface_type == NULL || interface_type->debug_name == NULL) {
        return "<unknown>";
    }
    return interface_type->debug_name;
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
    rt_gc_trace_print_summary();
    rt_gc_reset_state();
}

RtThreadState* rt_thread_state(void) {
    return &g_thread_state;
}

void rt_trace_push(const char* function_name, const char* file_path, uint32_t line, uint32_t column) {
    RtTraceFrame* frame = (RtTraceFrame*)calloc(1, sizeof(RtTraceFrame));
    if (frame == NULL) {
        rt_panic("rt_trace_push: out of memory");
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
        rt_panic("rt_trace_pop: trace stack underflow");
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


const RtInterfaceImpl* rt_find_interface_impl(const RtType* concrete_type, const RtInterfaceType* interface_type) {
    if (concrete_type == NULL || interface_type == NULL) {
        return NULL;
    }

    const RtInterfaceImpl* interfaces = concrete_type->interfaces;
    if (interfaces == NULL || concrete_type->interface_count == 0u) {
        return NULL;
    }

    for (uint32_t index = 0; index < concrete_type->interface_count; index++) {
        const RtInterfaceImpl* impl = &interfaces[index];
        if (impl->interface_type == interface_type) {
            return impl;
        }
    }

    return NULL;
}

void* rt_lookup_interface_method(void* obj, const RtInterfaceType* interface_type, uint32_t slot) {
    if (obj == NULL) {
        rt_panic_null_deref();
    }
    if (interface_type == NULL) {
        rt_panic("rt_lookup_interface_method called with NULL interface_type");
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    const RtInterfaceImpl* impl = rt_find_interface_impl(header->type, interface_type);
    if (impl == NULL) {
        rt_panic_bad_cast(
            rt_type_name_or_unknown(header->type),
            rt_interface_name_or_unknown(interface_type)
        );
    }
    if (impl->method_table == NULL || slot >= impl->method_count || slot >= interface_type->method_count) {
        rt_panic("rt_lookup_interface_method: invalid interface method slot");
    }

    const void* const* method_table = (const void* const*)impl->method_table;
    const void* method = method_table[slot];
    if (method == NULL) {
        rt_panic("rt_lookup_interface_method: null interface method entry");
    }
    return (void*)method;
}

void* rt_checked_cast_interface(void* obj, const RtInterfaceType* expected_interface) {
    if (obj == NULL) {
        return NULL;
    }
    if (expected_interface == NULL) {
        rt_panic("rt_checked_cast_interface called with NULL expected_interface");
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    if (rt_find_interface_impl(header->type, expected_interface) != NULL) {
        return obj;
    }

    rt_panic_bad_cast(
        rt_type_name_or_unknown(header->type),
        rt_interface_name_or_unknown(expected_interface)
    );
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

uint64_t rt_obj_same_type(void* lhs, void* rhs) {
    if (lhs == NULL || rhs == NULL) {
        return 0u;
    }

    RtObjHeader* lhs_header = (RtObjHeader*)lhs;
    RtObjHeader* rhs_header = (RtObjHeader*)rhs;
    return lhs_header->type == rhs_header->type ? 1u : 0u;
}
