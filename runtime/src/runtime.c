#include "runtime.h"
#include "gc_trace.h"

#include <math.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum {
    RT_TRACE_FRAME_INITIAL_CAPACITY = 8,
};

typedef struct RtSmallObjectFreelistNode {
    struct RtSmallObjectFreelistNode* next;
} RtSmallObjectFreelistNode;

static RtThreadState g_thread_state = {0};
static RtSmallObjectFreelistStats g_small_object_freelist_stats = {0};
static RtSmallObjectFreelistNode* g_small_object_freelist_heads[RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT] = {0};

static const uint64_t RT_SMALL_OBJECT_FREELIST_BUCKET_SIZES[RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT] = {
    32u,
    40u,
    48u,
    64u,
    80u,
    96u,
    128u,
};

static void rt_counter_inc_u64(uint64_t* value) {
    if (*value != UINT64_MAX) {
        (*value)++;
    }
}

static void rt_small_object_freelist_fill_bucket_sizes(RtSmallObjectFreelistStats* stats) {
    stats->bucket_count = RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT;
    for (uint32_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        stats->buckets[index].object_size_bytes = RT_SMALL_OBJECT_FREELIST_BUCKET_SIZES[index];
    }
}

static int rt_small_object_freelist_bucket_for_size(uint64_t total_bytes, uint32_t* out_index) {
    for (uint32_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        if (RT_SMALL_OBJECT_FREELIST_BUCKET_SIZES[index] == total_bytes) {
            *out_index = index;
            return 1;
        }
    }
    return 0;
}

static int rt_small_object_freelist_type_is_fixed_size(const RtType* type, uint64_t total_bytes) {
    if ((type->flags & RT_TYPE_FLAG_VARIABLE_SIZE) != 0u) {
        return 0;
    }
    return type->fixed_size_bytes == total_bytes;
}

static int rt_small_object_freelist_classify_allocation(
    const RtType* type,
    uint64_t total_bytes,
    uint32_t* out_bucket_index
) {
    if ((type->flags & RT_TYPE_FLAG_VARIABLE_SIZE) != 0u) {
        rt_counter_inc_u64(&g_small_object_freelist_stats.variable_size_requests);
        return 0;
    }

    uint32_t bucket_index = 0u;
    if (
        !rt_small_object_freelist_type_is_fixed_size(type, total_bytes)
        || !rt_small_object_freelist_bucket_for_size(total_bytes, &bucket_index)
    ) {
        rt_counter_inc_u64(&g_small_object_freelist_stats.unsupported_size_requests);
        return 0;
    }

    RtSmallObjectFreelistBucketStats* bucket = &g_small_object_freelist_stats.buckets[bucket_index];
    rt_counter_inc_u64(&g_small_object_freelist_stats.eligible_requests);
    rt_counter_inc_u64(&bucket->allocation_requests);
    *out_bucket_index = bucket_index;
    return 1;
}

static RtObjHeader* rt_small_object_freelist_pop(uint32_t bucket_index) {
    RtSmallObjectFreelistBucketStats* bucket = &g_small_object_freelist_stats.buckets[bucket_index];
    RtSmallObjectFreelistNode* node = g_small_object_freelist_heads[bucket_index];
    if (node == NULL) {
        rt_counter_inc_u64(&bucket->freelist_misses);
        return NULL;
    }

    g_small_object_freelist_heads[bucket_index] = node->next;
    if (bucket->retained_objects > 0u) {
        bucket->retained_objects--;
    }
    rt_counter_inc_u64(&bucket->freelist_hits);

    uint64_t total_bytes = RT_SMALL_OBJECT_FREELIST_BUCKET_SIZES[bucket_index];
    memset(node, 0, (size_t)total_bytes);
    return (RtObjHeader*)node;
}

static RtObjHeader* rt_alloc_zeroed_fallback(uint64_t total_bytes) {
    RtObjHeader* obj = (RtObjHeader*)calloc(1, (size_t)total_bytes);
    if (obj != NULL) {
        rt_counter_inc_u64(&g_small_object_freelist_stats.fallback_allocations);
    }
    return obj;
}

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

static RtObjHeader* rt_try_alloc_zeroed(const RtType* type, uint64_t total_bytes) {
    uint32_t bucket_index = 0u;
    int can_use_freelist = rt_small_object_freelist_classify_allocation(type, total_bytes, &bucket_index);
    if (can_use_freelist) {
        RtObjHeader* obj = rt_small_object_freelist_pop(bucket_index);
        if (obj != NULL) {
            return obj;
        }
    }

    RtObjHeader* obj = rt_alloc_zeroed_fallback(total_bytes);
    if (obj != NULL) {
        return obj;
    }

    rt_gc_collect();
    if (can_use_freelist) {
        obj = rt_small_object_freelist_pop(bucket_index);
        if (obj != NULL) {
            return obj;
        }
    }
    return rt_alloc_zeroed_fallback(total_bytes);
}

RtSmallObjectFreelistStats rt_gc_get_small_object_freelist_stats(void) {
    RtSmallObjectFreelistStats stats = g_small_object_freelist_stats;
    rt_small_object_freelist_fill_bucket_sizes(&stats);
    return stats;
}

void rt_gc_reset_small_object_freelist_stats(void) {
    uint64_t retained_objects[RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT] = {0};
    for (uint32_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        retained_objects[index] = g_small_object_freelist_stats.buckets[index].retained_objects;
    }

    g_small_object_freelist_stats = (RtSmallObjectFreelistStats){0};

    for (uint32_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        g_small_object_freelist_stats.buckets[index].retained_objects = retained_objects[index];
    }
}

void rt_gc_reset_small_object_freelist_state(void) {
    for (uint32_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        RtSmallObjectFreelistNode* node = g_small_object_freelist_heads[index];
        while (node != NULL) {
            RtSmallObjectFreelistNode* next = node->next;
            free(node);
            node = next;
        }
        g_small_object_freelist_heads[index] = NULL;
    }
    g_small_object_freelist_stats = (RtSmallObjectFreelistStats){0};
}

#ifdef NIF_RUNTIME_TESTING
void* rt_dbg_seed_small_object_freelist(uint64_t object_size_bytes, unsigned char fill_byte) {
    uint32_t bucket_index = 0u;
    if (!rt_small_object_freelist_bucket_for_size(object_size_bytes, &bucket_index)) {
        return NULL;
    }

    RtSmallObjectFreelistNode* node = (RtSmallObjectFreelistNode*)malloc((size_t)object_size_bytes);
    if (node == NULL) {
        rt_panic_oom();
    }

    memset(node, fill_byte, (size_t)object_size_bytes);
    node->next = g_small_object_freelist_heads[bucket_index];
    g_small_object_freelist_heads[bucket_index] = node;

    RtSmallObjectFreelistBucketStats* bucket = &g_small_object_freelist_stats.buckets[bucket_index];
    rt_counter_inc_u64(&bucket->returned_objects);
    rt_counter_inc_u64(&bucket->retained_objects);
    return node;
}
#endif

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
    rt_gc_maybe_collect(total);

    RtObjHeader* obj = rt_try_alloc_zeroed(type, total);
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
