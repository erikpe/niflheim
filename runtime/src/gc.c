#include "runtime.h"

#include <limits.h>
#include <stddef.h>
#include <stdlib.h>


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
static uint64_t g_allocated_bytes = 0;
static uint64_t g_live_bytes = 0;
static uint64_t g_next_gc_threshold = 64u * 1024u;
static uint64_t g_tracked_object_count = 0;

enum {
    RT_GC_MIN_THRESHOLD_BYTES = 64u * 1024u,
    RT_GC_GROWTH_NUM = 2u,
    RT_GC_GROWTH_DEN = 1u,
};


static uint64_t rt_saturating_add_u64(uint64_t a, uint64_t b) {
    if (UINT64_MAX - a < b) {
        return UINT64_MAX;
    }
    return a + b;
}


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
    for (RtTrackedObject* node = g_tracked_objects; node != NULL; node = node->next) {
        if (node->obj == candidate) {
            return 1;
        }
    }
    return 0;
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
        rt_gc_collect(ts);
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

    g_allocated_bytes = 0;
    g_live_bytes = 0;
    g_next_gc_threshold = RT_GC_MIN_THRESHOLD_BYTES;
    g_tracked_object_count = 0;
}


RtGcStats rt_gc_get_stats(void) {
    RtGcStats stats;
    stats.allocated_bytes = g_allocated_bytes;
    stats.live_bytes = g_live_bytes;
    stats.next_gc_threshold = g_next_gc_threshold;
    stats.tracked_object_count = g_tracked_object_count;
    return stats;
}

void rt_gc_collect(RtThreadState* ts) {
    if (ts == NULL) {
        ts = rt_thread_state();
    }

    rt_clear_all_marks();
    rt_mark_from_global_roots();
    rt_mark_from_shadow_stack(ts);

    g_live_bytes = rt_sweep_unmarked();
    g_allocated_bytes = g_live_bytes;
    rt_update_threshold_from_live(g_live_bytes);
}
