#include "runtime.h"

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


void rt_gc_track_allocation(RtObjHeader* obj) {
    RtTrackedObject* node = (RtTrackedObject*)malloc(sizeof(RtTrackedObject));
    if (node == NULL) {
        rt_panic_oom();
    }

    node->obj = obj;
    node->next = g_tracked_objects;
    g_tracked_objects = node;
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
}

void rt_gc_collect(RtThreadState* ts);

void rt_gc_collect(RtThreadState* ts) {
    rt_clear_all_marks();
    rt_mark_from_global_roots();
    rt_mark_from_shadow_stack(ts);
}
