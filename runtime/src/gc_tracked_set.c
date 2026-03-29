#include "gc_tracked_set.h"

#include "panic.h"

#include <limits.h>
#include <stdint.h>
#include <stdlib.h>


enum {
    RT_TRACKED_SET_INITIAL_CAPACITY = 1024u,
};

#define RT_TRACKED_SET_TOMBSTONE ((RtObjHeader*)(uintptr_t)1)


static RtObjHeader** g_tracked_set_slots = NULL;
static uint64_t g_tracked_set_capacity = 0;
static uint64_t g_tracked_set_size = 0;
static uint64_t g_tracked_set_occupied = 0;


static uint64_t rt_hash_ptr_uint64(uintptr_t value) {
    uint64_t x = (uint64_t)value;
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdu;
    x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53u;
    x ^= x >> 33;
    return x;
}


static void rt_insert_into_slots(RtObjHeader** slots, uint64_t capacity, RtObjHeader* obj) {
    if (slots == NULL || capacity == 0u || obj == NULL) {
        return;
    }

    uint64_t mask = capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    while (slots[index] != NULL) {
        index = (index + 1u) & mask;
    }
    slots[index] = obj;
}


static void rt_tracked_set_rebuild(uint64_t new_capacity) {
    if (new_capacity < RT_TRACKED_SET_INITIAL_CAPACITY) {
        new_capacity = RT_TRACKED_SET_INITIAL_CAPACITY;
    }

    RtObjHeader** new_slots = (RtObjHeader**)calloc((size_t)new_capacity, sizeof(RtObjHeader*));
    if (new_slots == NULL) {
        rt_panic_oom();
    }

    uint64_t new_size = 0u;
    for (uint64_t i = 0u; i < g_tracked_set_capacity; i++) {
        RtObjHeader* obj = g_tracked_set_slots[i];
        if (obj == NULL || obj == RT_TRACKED_SET_TOMBSTONE) {
            continue;
        }
        rt_insert_into_slots(new_slots, new_capacity, obj);
        new_size++;
    }

    free(g_tracked_set_slots);
    g_tracked_set_slots = new_slots;
    g_tracked_set_capacity = new_capacity;
    g_tracked_set_size = new_size;
    g_tracked_set_occupied = new_size;
}


static void rt_tracked_set_ensure_capacity_for_insert(void) {
    if (g_tracked_set_capacity == 0u) {
        rt_tracked_set_rebuild(RT_TRACKED_SET_INITIAL_CAPACITY);
        return;
    }

    uint64_t threshold = (g_tracked_set_capacity * 7u) / 10u;
    if (g_tracked_set_occupied + 1u > threshold) {
        uint64_t new_capacity = g_tracked_set_capacity;
        if (g_tracked_set_size + 1u > threshold) {
            new_capacity = g_tracked_set_capacity * 2u;
        }
        rt_tracked_set_rebuild(new_capacity);
        return;
    }

    if (g_tracked_set_size + 1u > threshold) {
        rt_tracked_set_rebuild(g_tracked_set_capacity * 2u);
    }
}


static uint64_t rt_tracked_set_find_slot(const RtObjHeader* obj, int* out_found) {
    if (out_found != NULL) {
        *out_found = 0;
    }
    if (obj == NULL || g_tracked_set_capacity == 0u) {
        return UINT64_MAX;
    }

    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    uint64_t first_tombstone = UINT64_MAX;

    for (uint64_t probes = 0u; probes < g_tracked_set_capacity; probes++) {
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            return (first_tombstone != UINT64_MAX) ? first_tombstone : index;
        }
        if (slot == RT_TRACKED_SET_TOMBSTONE) {
            if (first_tombstone == UINT64_MAX) {
                first_tombstone = index;
            }
        } else if (slot == obj) {
            if (out_found != NULL) {
                *out_found = 1;
            }
            return index;
        }
        index = (index + 1u) & mask;
    }

    return first_tombstone;
}


void rt_gc_tracked_set_insert(RtObjHeader* obj) {
    if (obj == NULL) {
        return;
    }

    rt_tracked_set_ensure_capacity_for_insert();

    int found = 0;
    uint64_t index = rt_tracked_set_find_slot(obj, &found);
    if (found || index == UINT64_MAX) {
        return;
    }

    if (g_tracked_set_slots[index] == NULL) {
        g_tracked_set_occupied++;
    }
    g_tracked_set_slots[index] = obj;
    g_tracked_set_size++;
}


int rt_gc_tracked_set_contains(const RtObjHeader* obj) {
    int found = 0;
    (void)rt_tracked_set_find_slot(obj, &found);
    return found;
}


void rt_gc_tracked_set_remove(RtObjHeader* obj) {
    int found = 0;
    uint64_t index = rt_tracked_set_find_slot(obj, &found);
    if (!found || index == UINT64_MAX) {
        return;
    }

    g_tracked_set_slots[index] = RT_TRACKED_SET_TOMBSTONE;
    if (g_tracked_set_size > 0u) {
        g_tracked_set_size--;
    }
}


void rt_gc_tracked_set_reset(void) {
    free(g_tracked_set_slots);
    g_tracked_set_slots = NULL;
    g_tracked_set_capacity = 0u;
    g_tracked_set_size = 0u;
    g_tracked_set_occupied = 0u;
}
