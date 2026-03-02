#include "runtime.h"

#include <inttypes.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>


typedef struct RtTrackedObject {
    RtObjHeader* obj;
    struct RtTrackedObject* next;
} RtTrackedObject;


typedef struct RtGlobalRoot {
    void** slot;
    struct RtGlobalRoot* next;
} RtGlobalRoot;


static RtTrackedObject* g_tracked_objects = NULL;
static RtGlobalRoot* g_global_roots = NULL;
static RtObjHeader** g_tracked_set_slots = NULL;
static uint64_t g_tracked_set_capacity = 0;
static uint64_t g_tracked_set_size = 0;
static uint64_t g_allocated_bytes = 0;
static uint64_t g_live_bytes = 0;
static uint64_t g_next_gc_threshold = 64u * 1024u;
static uint64_t g_tracked_object_count = 0;
static uint64_t g_gc_cycle_count = 0;
static int g_gc_trace_enabled = -1;
static uint64_t g_gc_timing_start_ns = 0;
static uint64_t g_gc_total_collect_ns = 0;
static uint64_t g_gc_total_mark_ns = 0;
static uint64_t g_gc_total_sweep_ns = 0;

enum {
    RT_GC_MIN_THRESHOLD_BYTES = 64u * 1024u,
    RT_GC_GROWTH_NUM = 2u,
    RT_GC_GROWTH_DEN = 1u,
    RT_TRACKED_SET_INITIAL_CAPACITY = 1024u,
};

#define RT_TRACKED_SET_TOMBSTONE ((RtObjHeader*)(uintptr_t)1)


static uint64_t rt_saturating_add_u64(uint64_t a, uint64_t b) {
    if (UINT64_MAX - a < b) {
        return UINT64_MAX;
    }
    return a + b;
}


static uint64_t rt_hash_ptr_uint64(uintptr_t value) {
    uint64_t x = (uint64_t)value;
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdu;
    x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53u;
    x ^= x >> 33;
    return x;
}


static uint64_t rt_next_power_of_two_at_least(uint64_t value) {
    uint64_t out = 1u;
    while (out < value && out < (UINT64_MAX / 2u)) {
        out <<= 1u;
    }
    return out;
}


static void rt_tracked_set_rebuild(uint64_t new_capacity) {
    if (new_capacity < RT_TRACKED_SET_INITIAL_CAPACITY) {
        new_capacity = RT_TRACKED_SET_INITIAL_CAPACITY;
    }
    new_capacity = rt_next_power_of_two_at_least(new_capacity);

    RtObjHeader** new_slots = (RtObjHeader**)calloc((size_t)new_capacity, sizeof(RtObjHeader*));
    if (new_slots == NULL) {
        rt_panic_oom();
    }

    uint64_t new_mask = new_capacity - 1u;
    for (RtTrackedObject* node = g_tracked_objects; node != NULL; node = node->next) {
        RtObjHeader* obj = node->obj;
        if (obj == NULL) {
            continue;
        }
        uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & new_mask;
        while (new_slots[index] != NULL) {
            index = (index + 1u) & new_mask;
        }
        new_slots[index] = obj;
    }

    free(g_tracked_set_slots);
    g_tracked_set_slots = new_slots;
    g_tracked_set_capacity = new_capacity;
    g_tracked_set_size = g_tracked_object_count;
}


static void rt_tracked_set_ensure_capacity_for_insert(void) {
    if (g_tracked_set_capacity == 0u) {
        rt_tracked_set_rebuild(RT_TRACKED_SET_INITIAL_CAPACITY);
        return;
    }

    uint64_t threshold = (g_tracked_set_capacity * 7u) / 10u;
    if (g_tracked_set_size + 1u > threshold) {
        rt_tracked_set_rebuild(g_tracked_set_capacity * 2u);
    }
}


static void rt_tracked_set_insert(RtObjHeader* obj) {
    if (obj == NULL) {
        return;
    }

    rt_tracked_set_ensure_capacity_for_insert();
    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    uint64_t first_tombstone = UINT64_MAX;

    while (1) {
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            uint64_t target = (first_tombstone != UINT64_MAX) ? first_tombstone : index;
            g_tracked_set_slots[target] = obj;
            g_tracked_set_size = rt_saturating_add_u64(g_tracked_set_size, 1u);
            return;
        }
        if (slot == RT_TRACKED_SET_TOMBSTONE) {
            if (first_tombstone == UINT64_MAX) {
                first_tombstone = index;
            }
        } else if (slot == obj) {
            return;
        }
        index = (index + 1u) & mask;
    }
}


static int rt_tracked_set_contains(const RtObjHeader* obj) {
    if (obj == NULL || g_tracked_set_capacity == 0u) {
        return 0;
    }

    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    while (1) {
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            return 0;
        }
        if (slot != RT_TRACKED_SET_TOMBSTONE && slot == obj) {
            return 1;
        }
        index = (index + 1u) & mask;
    }
}


static void rt_tracked_set_remove(RtObjHeader* obj) {
    if (obj == NULL || g_tracked_set_capacity == 0u) {
        return;
    }

    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    while (1) {
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            return;
        }
        if (slot != RT_TRACKED_SET_TOMBSTONE && slot == obj) {
            g_tracked_set_slots[index] = RT_TRACKED_SET_TOMBSTONE;
            if (g_tracked_set_size > 0u) {
                g_tracked_set_size--;
            }
            return;
        }
        index = (index + 1u) & mask;
    }
}


static uint64_t rt_time_now_ns(void) {
    struct timespec ts;
    if (timespec_get(&ts, TIME_UTC) != TIME_UTC) {
        return 0;
    }
    uint64_t sec_ns = rt_saturating_add_u64((uint64_t)ts.tv_sec, 0u);
    if (sec_ns > UINT64_MAX / 1000000000u) {
        return UINT64_MAX;
    }
    sec_ns *= 1000000000u;
    return rt_saturating_add_u64(sec_ns, (uint64_t)ts.tv_nsec);
}


static uint64_t rt_ms_whole_from_ns(uint64_t ns) {
    return ns / 1000000u;
}


static uint64_t rt_ms_frac3_from_ns(uint64_t ns) {
    return (ns / 1000u) % 1000u;
}


static uint64_t rt_pct_basis_points(uint64_t part, uint64_t whole) {
    if (whole == 0u) {
        return 0u;
    }
    long double scaled = ((long double)part * 10000.0L) / (long double)whole;
    if (scaled <= 0.0L) {
        return 0u;
    }
    if (scaled >= (long double)UINT64_MAX) {
        return UINT64_MAX;
    }
    return (uint64_t)scaled;
}


static uint64_t rt_pct_whole_from_bps(uint64_t bps) {
    return bps / 100u;
}


static uint64_t rt_pct_frac2_from_bps(uint64_t bps) {
    return bps % 100u;
}


static int rt_gc_trace_is_enabled(void) {
    if (g_gc_trace_enabled >= 0) {
        return g_gc_trace_enabled;
    }

    const char* value = getenv("NIF_GC_TRACE");
    if (value == NULL || value[0] == '\0' || value[0] == '0') {
        g_gc_trace_enabled = 0;
    } else {
        g_gc_trace_enabled = 1;
    }
    return g_gc_trace_enabled;
}


static void rt_gc_collect_impl(
    RtThreadState* ts,
    const char* reason,
    uint64_t upcoming_bytes,
    uint64_t projected_bytes,
    uint64_t threshold_before
);


static uint64_t rt_scaled_live_bytes(uint64_t live_bytes) {
    if (live_bytes > UINT64_MAX / RT_GC_GROWTH_NUM) {
        return UINT64_MAX;
    }
    return (live_bytes * RT_GC_GROWTH_NUM) / RT_GC_GROWTH_DEN;
}


static void rt_update_threshold_from_live(uint64_t live_bytes) {
    uint64_t next = rt_scaled_live_bytes(live_bytes);
    if (next < RT_GC_MIN_THRESHOLD_BYTES) {
        next = RT_GC_MIN_THRESHOLD_BYTES;
    }
    g_next_gc_threshold = next;
}


static int rt_is_tracked_object(const RtObjHeader* candidate) {
    return rt_tracked_set_contains(candidate);
}


static RtObjHeader* rt_as_tracked_object(void* ref) {
    if (ref == NULL) {
        return NULL;
    }

    RtObjHeader* candidate = (RtObjHeader*)ref;
    if (!rt_is_tracked_object(candidate)) {
        return NULL;
    }
    return candidate;
}


static void rt_mark_object(RtObjHeader* obj);


static void rt_mark_ref_slot(void** slot) {
    if (slot == NULL) {
        return;
    }

    RtObjHeader* child = rt_as_tracked_object(*slot);
    if (child != NULL) {
        rt_mark_object(child);
    }
}


static void rt_mark_object(RtObjHeader* obj) {
    if (obj == NULL) {
        return;
    }

    if ((obj->gc_flags & RT_GC_FLAG_MARKED) != 0u) {
        return;
    }
    obj->gc_flags |= RT_GC_FLAG_MARKED;

    const RtType* type = obj->type;
    if (type == NULL) {
        return;
    }

    if (type->trace_fn != NULL) {
        type->trace_fn((void*)obj, rt_mark_ref_slot);
        return;
    }

    if (type->pointer_offsets != NULL && type->pointer_offsets_count > 0) {
        const unsigned char* base = (const unsigned char*)obj;
        for (uint32_t i = 0; i < type->pointer_offsets_count; i++) {
            uint32_t offset = type->pointer_offsets[i];
            void** slot = (void**)(void*)(base + offset);
            rt_mark_ref_slot(slot);
        }
    }
}


static void rt_clear_all_marks(void) {
    for (RtTrackedObject* node = g_tracked_objects; node != NULL; node = node->next) {
        node->obj->gc_flags &= ~RT_GC_FLAG_MARKED;
    }
}


static void rt_mark_from_global_roots(void) {
    for (RtGlobalRoot* root = g_global_roots; root != NULL; root = root->next) {
        rt_mark_ref_slot(root->slot);
    }
}


static void rt_mark_from_shadow_stack(RtThreadState* ts) {
    if (ts == NULL) {
        return;
    }

    for (RtRootFrame* frame = ts->roots_top; frame != NULL; frame = frame->prev) {
        for (uint32_t i = 0; i < frame->slot_count; i++) {
            rt_mark_ref_slot(&frame->slots[i]);
        }
    }
}


static uint64_t rt_sweep_unmarked(void) {
    uint64_t live_bytes = 0;
    RtTrackedObject** current = &g_tracked_objects;

    while (*current != NULL) {
        RtTrackedObject* node = *current;
        RtObjHeader* obj = node->obj;

        if (obj == NULL) {
            *current = node->next;
            free(node);
            if (g_tracked_object_count > 0) {
                g_tracked_object_count--;
            }
            continue;
        }

        const int marked = (obj->gc_flags & RT_GC_FLAG_MARKED) != 0u;
        const int pinned = (obj->gc_flags & RT_GC_FLAG_PINNED) != 0u;
        if (marked || pinned) {
            obj->gc_flags &= ~RT_GC_FLAG_MARKED;
            live_bytes = rt_saturating_add_u64(live_bytes, obj->size_bytes);
            current = &node->next;
            continue;
        }

        *current = node->next;
        rt_tracked_set_remove(obj);
        free(obj);
        free(node);
        if (g_tracked_object_count > 0) {
            g_tracked_object_count--;
        }
    }

    return live_bytes;
}


void rt_gc_maybe_collect(RtThreadState* ts, uint64_t upcoming_bytes) {
    if (ts == NULL) {
        ts = rt_thread_state();
    }

    const uint64_t projected = rt_saturating_add_u64(g_allocated_bytes, upcoming_bytes);
    if (projected >= g_next_gc_threshold) {
        rt_gc_collect_impl(ts, "threshold", upcoming_bytes, projected, g_next_gc_threshold);
    }
}


void rt_gc_track_allocation(RtObjHeader* obj) {
    RtTrackedObject* node = (RtTrackedObject*)malloc(sizeof(RtTrackedObject));
    if (node == NULL) {
        rt_panic_oom();
    }

    node->obj = obj;
    node->next = g_tracked_objects;
    g_tracked_objects = node;

    rt_tracked_set_insert(obj);
    g_allocated_bytes = rt_saturating_add_u64(g_allocated_bytes, obj->size_bytes);
    g_tracked_object_count = rt_saturating_add_u64(g_tracked_object_count, 1);
}


void rt_gc_register_global_root(void** slot) {
    if (slot == NULL) {
        rt_panic("rt_gc_register_global_root: slot is NULL");
    }

    for (RtGlobalRoot* node = g_global_roots; node != NULL; node = node->next) {
        if (node->slot == slot) {
            return;
        }
    }

    RtGlobalRoot* node = (RtGlobalRoot*)malloc(sizeof(RtGlobalRoot));
    if (node == NULL) {
        rt_panic_oom();
    }

    node->slot = slot;
    node->next = g_global_roots;
    g_global_roots = node;
}


void rt_gc_unregister_global_root(void** slot) {
    if (slot == NULL) {
        rt_panic("rt_gc_unregister_global_root: slot is NULL");
    }

    RtGlobalRoot** current = &g_global_roots;
    while (*current != NULL) {
        RtGlobalRoot* node = *current;
        if (node->slot == slot) {
            *current = node->next;
            free(node);
            return;
        }
        current = &node->next;
    }
}


void rt_gc_reset_state(void) {
    RtTrackedObject* object_node = g_tracked_objects;
    while (object_node != NULL) {
        RtTrackedObject* next = object_node->next;
        free(object_node->obj);
        free(object_node);
        object_node = next;
    }
    g_tracked_objects = NULL;

    RtGlobalRoot* root_node = g_global_roots;
    while (root_node != NULL) {
        RtGlobalRoot* next = root_node->next;
        free(root_node);
        root_node = next;
    }
    g_global_roots = NULL;

    free(g_tracked_set_slots);
    g_tracked_set_slots = NULL;
    g_tracked_set_capacity = 0;
    g_tracked_set_size = 0;

    g_allocated_bytes = 0;
    g_live_bytes = 0;
    g_next_gc_threshold = RT_GC_MIN_THRESHOLD_BYTES;
    g_tracked_object_count = 0;
    g_gc_cycle_count = 0;
    g_gc_timing_start_ns = 0;
    g_gc_total_collect_ns = 0;
    g_gc_total_mark_ns = 0;
    g_gc_total_sweep_ns = 0;
}


RtGcStats rt_gc_get_stats(void) {
    RtGcStats stats;
    stats.allocated_bytes = g_allocated_bytes;
    stats.live_bytes = g_live_bytes;
    stats.next_gc_threshold = g_next_gc_threshold;
    stats.tracked_object_count = g_tracked_object_count;
    return stats;
}


void rt_gc_trace_print_summary(void) {
    if (!rt_gc_trace_is_enabled()) {
        return;
    }
    if (g_gc_cycle_count == 0 || g_gc_timing_start_ns == 0) {
        fprintf(
            stderr,
            "[gc] summary cycles=0 wall=0.000ms"
            " total_collect=0.000ms(0.00%%) total_mark=0.000ms(0.00%%)"
            " total_sweep=0.000ms(0.00%%) outside_gc=0.000ms(0.00%%)\n"
        );
        return;
    }

    uint64_t now_ns = rt_time_now_ns();
    uint64_t total_window_ns = 0;
    if (now_ns >= g_gc_timing_start_ns) {
        total_window_ns = now_ns - g_gc_timing_start_ns;
    }
    uint64_t outside_gc_ns = 0;
    if (total_window_ns >= g_gc_total_collect_ns) {
        outside_gc_ns = total_window_ns - g_gc_total_collect_ns;
    }

    const uint64_t wall_ms_whole = rt_ms_whole_from_ns(total_window_ns);
    const uint64_t wall_ms_frac = rt_ms_frac3_from_ns(total_window_ns);
    const uint64_t collect_ms_whole = rt_ms_whole_from_ns(g_gc_total_collect_ns);
    const uint64_t collect_ms_frac = rt_ms_frac3_from_ns(g_gc_total_collect_ns);
    const uint64_t mark_ms_whole = rt_ms_whole_from_ns(g_gc_total_mark_ns);
    const uint64_t mark_ms_frac = rt_ms_frac3_from_ns(g_gc_total_mark_ns);
    const uint64_t sweep_ms_whole = rt_ms_whole_from_ns(g_gc_total_sweep_ns);
    const uint64_t sweep_ms_frac = rt_ms_frac3_from_ns(g_gc_total_sweep_ns);
    const uint64_t outside_ms_whole = rt_ms_whole_from_ns(outside_gc_ns);
    const uint64_t outside_ms_frac = rt_ms_frac3_from_ns(outside_gc_ns);

    const uint64_t collect_bps = rt_pct_basis_points(g_gc_total_collect_ns, total_window_ns);
    const uint64_t mark_bps = rt_pct_basis_points(g_gc_total_mark_ns, total_window_ns);
    const uint64_t sweep_bps = rt_pct_basis_points(g_gc_total_sweep_ns, total_window_ns);
    const uint64_t outside_bps = rt_pct_basis_points(outside_gc_ns, total_window_ns);

    fprintf(
        stderr,
        "[gc] summary cycles=%" PRIu64 " wall=%" PRIu64 ".%03" PRIu64 "ms"
        " total_collect=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " total_mark=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " total_sweep=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " outside_gc=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)\n",
        g_gc_cycle_count,
        wall_ms_whole,
        wall_ms_frac,
        collect_ms_whole,
        collect_ms_frac,
        rt_pct_whole_from_bps(collect_bps),
        rt_pct_frac2_from_bps(collect_bps),
        mark_ms_whole,
        mark_ms_frac,
        rt_pct_whole_from_bps(mark_bps),
        rt_pct_frac2_from_bps(mark_bps),
        sweep_ms_whole,
        sweep_ms_frac,
        rt_pct_whole_from_bps(sweep_bps),
        rt_pct_frac2_from_bps(sweep_bps),
        outside_ms_whole,
        outside_ms_frac,
        rt_pct_whole_from_bps(outside_bps),
        rt_pct_frac2_from_bps(outside_bps)
    );
}

static void rt_gc_collect_impl(
    RtThreadState* ts,
    const char* reason,
    uint64_t upcoming_bytes,
    uint64_t projected_bytes,
    uint64_t threshold_before
) {
    if (ts == NULL) {
        ts = rt_thread_state();
    }

    const uint64_t before_allocated = g_allocated_bytes;
    const uint64_t before_live = g_live_bytes;
    const uint64_t before_tracked = g_tracked_object_count;
    const uint64_t cycle = g_gc_cycle_count + 1u;
    const int trace_enabled = rt_gc_trace_is_enabled();

    uint64_t collect_start_ns = 0;
    if (trace_enabled) {
        collect_start_ns = rt_time_now_ns();
        if (g_gc_timing_start_ns == 0) {
            g_gc_timing_start_ns = collect_start_ns;
        }
    }

    if (trace_enabled) {
        fprintf(
            stderr,
            "[gc] cycle=%" PRIu64 " phase=start reason=%s allocated=%" PRIu64
            " live=%" PRIu64 " tracked=%" PRIu64 " threshold=%" PRIu64
            " upcoming=%" PRIu64 " projected=%" PRIu64 "\n",
            cycle,
            reason,
            before_allocated,
            before_live,
            before_tracked,
            threshold_before,
            upcoming_bytes,
            projected_bytes
        );
    }

    uint64_t mark_start_ns = 0;
    uint64_t mark_end_ns = 0;
    if (trace_enabled) {
        mark_start_ns = rt_time_now_ns();
    }
    rt_clear_all_marks();
    rt_mark_from_global_roots();
    rt_mark_from_shadow_stack(ts);
    if (trace_enabled) {
        mark_end_ns = rt_time_now_ns();
    }

    uint64_t sweep_start_ns = 0;
    uint64_t sweep_end_ns = 0;
    if (trace_enabled) {
        sweep_start_ns = rt_time_now_ns();
    }
    g_live_bytes = rt_sweep_unmarked();
    if (trace_enabled) {
        sweep_end_ns = rt_time_now_ns();
    }
    g_allocated_bytes = g_live_bytes;
    rt_update_threshold_from_live(g_live_bytes);
    g_gc_cycle_count = cycle;

    const uint64_t collected_bytes = before_allocated >= g_live_bytes
        ? (before_allocated - g_live_bytes)
        : 0u;
    const uint64_t collected_objects = before_tracked >= g_tracked_object_count
        ? (before_tracked - g_tracked_object_count)
        : 0u;

    uint64_t mark_ns = 0;
    uint64_t sweep_ns = 0;
    uint64_t collect_ns = 0;
    uint64_t total_window_ns = 0;
    uint64_t outside_gc_ns = 0;
    if (trace_enabled) {
        if (mark_end_ns >= mark_start_ns) {
            mark_ns = mark_end_ns - mark_start_ns;
        }
        if (sweep_end_ns >= sweep_start_ns) {
            sweep_ns = sweep_end_ns - sweep_start_ns;
        }
        if (sweep_end_ns >= collect_start_ns) {
            collect_ns = sweep_end_ns - collect_start_ns;
        }

        g_gc_total_mark_ns = rt_saturating_add_u64(g_gc_total_mark_ns, mark_ns);
        g_gc_total_sweep_ns = rt_saturating_add_u64(g_gc_total_sweep_ns, sweep_ns);
        g_gc_total_collect_ns = rt_saturating_add_u64(g_gc_total_collect_ns, collect_ns);

        if (g_gc_timing_start_ns > 0 && sweep_end_ns >= g_gc_timing_start_ns) {
            total_window_ns = sweep_end_ns - g_gc_timing_start_ns;
        }
        if (total_window_ns >= g_gc_total_collect_ns) {
            outside_gc_ns = total_window_ns - g_gc_total_collect_ns;
        }
    }

    if (trace_enabled) {
        const uint64_t cycle_collect_ms_whole = rt_ms_whole_from_ns(collect_ns);
        const uint64_t cycle_collect_ms_frac = rt_ms_frac3_from_ns(collect_ns);
        const uint64_t cycle_mark_ms_whole = rt_ms_whole_from_ns(mark_ns);
        const uint64_t cycle_mark_ms_frac = rt_ms_frac3_from_ns(mark_ns);
        const uint64_t cycle_sweep_ms_whole = rt_ms_whole_from_ns(sweep_ns);
        const uint64_t cycle_sweep_ms_frac = rt_ms_frac3_from_ns(sweep_ns);
        const uint64_t cycle_mark_bps = rt_pct_basis_points(mark_ns, collect_ns);
        const uint64_t cycle_sweep_bps = rt_pct_basis_points(sweep_ns, collect_ns);

        const uint64_t wall_ms_whole = rt_ms_whole_from_ns(total_window_ns);
        const uint64_t wall_ms_frac = rt_ms_frac3_from_ns(total_window_ns);
        const uint64_t total_collect_ms_whole = rt_ms_whole_from_ns(g_gc_total_collect_ns);
        const uint64_t total_collect_ms_frac = rt_ms_frac3_from_ns(g_gc_total_collect_ns);
        const uint64_t total_mark_ms_whole = rt_ms_whole_from_ns(g_gc_total_mark_ns);
        const uint64_t total_mark_ms_frac = rt_ms_frac3_from_ns(g_gc_total_mark_ns);
        const uint64_t total_sweep_ms_whole = rt_ms_whole_from_ns(g_gc_total_sweep_ns);
        const uint64_t total_sweep_ms_frac = rt_ms_frac3_from_ns(g_gc_total_sweep_ns);
        const uint64_t outside_ms_whole = rt_ms_whole_from_ns(outside_gc_ns);
        const uint64_t outside_ms_frac = rt_ms_frac3_from_ns(outside_gc_ns);

        const uint64_t total_collect_bps = rt_pct_basis_points(g_gc_total_collect_ns, total_window_ns);
        const uint64_t total_mark_bps = rt_pct_basis_points(g_gc_total_mark_ns, total_window_ns);
        const uint64_t total_sweep_bps = rt_pct_basis_points(g_gc_total_sweep_ns, total_window_ns);
        const uint64_t outside_bps = rt_pct_basis_points(outside_gc_ns, total_window_ns);

        fprintf(
            stderr,
            "[gc] cycle=%" PRIu64 " phase=end reason=%s collected_bytes=%" PRIu64
            " collected_objects=%" PRIu64 " live=%" PRIu64
            " tracked=%" PRIu64 " next_threshold=%" PRIu64
            " cycle_collect=%" PRIu64 ".%03" PRIu64 "ms"
            " cycle_mark=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
            " cycle_sweep=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
            " wall=%" PRIu64 ".%03" PRIu64 "ms"
            " total_collect=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
            " total_mark=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
            " total_sweep=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
            " outside_gc=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)\n",
            cycle,
            reason,
            collected_bytes,
            collected_objects,
            g_live_bytes,
            g_tracked_object_count,
            g_next_gc_threshold,
            cycle_collect_ms_whole,
            cycle_collect_ms_frac,
            cycle_mark_ms_whole,
            cycle_mark_ms_frac,
            rt_pct_whole_from_bps(cycle_mark_bps),
            rt_pct_frac2_from_bps(cycle_mark_bps),
            cycle_sweep_ms_whole,
            cycle_sweep_ms_frac,
            rt_pct_whole_from_bps(cycle_sweep_bps),
            rt_pct_frac2_from_bps(cycle_sweep_bps),
            wall_ms_whole,
            wall_ms_frac,
            total_collect_ms_whole,
            total_collect_ms_frac,
            rt_pct_whole_from_bps(total_collect_bps),
            rt_pct_frac2_from_bps(total_collect_bps),
            total_mark_ms_whole,
            total_mark_ms_frac,
            rt_pct_whole_from_bps(total_mark_bps),
            rt_pct_frac2_from_bps(total_mark_bps),
            total_sweep_ms_whole,
            total_sweep_ms_frac,
            rt_pct_whole_from_bps(total_sweep_bps),
            rt_pct_frac2_from_bps(total_sweep_bps),
            outside_ms_whole,
            outside_ms_frac,
            rt_pct_whole_from_bps(outside_bps),
            rt_pct_frac2_from_bps(outside_bps)
        );
    }
}


void rt_gc_collect(RtThreadState* ts) {
    rt_gc_collect_impl(ts, "explicit", 0u, g_allocated_bytes, g_next_gc_threshold);
}
