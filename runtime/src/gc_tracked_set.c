#include "gc_tracked_set.h"

#include "panic.h"

#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>


enum {
    RT_TRACKED_SET_INITIAL_CAPACITY = 1024u,
    RT_TRACKED_SET_LOAD_NUM = 5u,
    RT_TRACKED_SET_LOAD_DEN = 10u,
    RT_TRACKED_SET_TOMBSTONE_COMPACT_DEN = 4u,
};

#define RT_TRACKED_SET_TOMBSTONE ((RtObjHeader*)(uintptr_t)1)


static RtObjHeader** g_tracked_set_slots = NULL;
static RtObjHeader** g_tracked_set_scratch_slots = NULL;
static uint64_t g_tracked_set_capacity = 0;
static uint64_t g_tracked_set_scratch_capacity = 0;
static uint64_t g_tracked_set_size = 0;
static uint64_t g_tracked_set_occupied = 0;
static RtGcTrackedSetProbeStats g_probe_stats = {0};
static int g_probe_stats_enabled = 0;


typedef enum RtTrackedSetProbeKind {
    RT_TRACKED_SET_PROBE_INSERT,
    RT_TRACKED_SET_PROBE_CONTAINS,
    RT_TRACKED_SET_PROBE_REMOVE,
} RtTrackedSetProbeKind;


typedef enum RtTrackedSetRebuildReason {
    RT_TRACKED_SET_REBUILD_INITIALIZE,
    RT_TRACKED_SET_REBUILD_GROW,
    RT_TRACKED_SET_REBUILD_COMPACT_OCCUPANCY,
    RT_TRACKED_SET_REBUILD_COMPACT_TOMBSTONES,
} RtTrackedSetRebuildReason;


typedef struct RtTrackedSetProbeResult {
    uint64_t index;
    uint64_t probes;
    int found;
} RtTrackedSetProbeResult;


static inline uint64_t rt_saturating_add_u64(uint64_t a, uint64_t b) {
    if (UINT64_MAX - a < b) {
        return UINT64_MAX;
    }
    return a + b;
}


static inline RtTrackedSetProbeResult rt_tracked_set_probe_result(uint64_t index, uint64_t probes, int found) {
    RtTrackedSetProbeResult result;
    result.index = index;
    result.probes = probes;
    result.found = found;
    return result;
}


static inline uint64_t rt_tracked_set_tombstone_count(void) {
    if (g_tracked_set_occupied <= g_tracked_set_size) {
        return 0u;
    }
    return g_tracked_set_occupied - g_tracked_set_size;
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


static inline void rt_tracked_set_record_probe(RtTrackedSetProbeKind kind, uint64_t probes) {
    if (!g_probe_stats_enabled) {
        return;
    }

    uint64_t* call_count = NULL;
    uint64_t* probe_total = NULL;
    switch (kind) {
        case RT_TRACKED_SET_PROBE_INSERT:
            call_count = &g_probe_stats.insert_calls;
            probe_total = &g_probe_stats.insert_probes;
            break;
        case RT_TRACKED_SET_PROBE_CONTAINS:
            call_count = &g_probe_stats.contains_calls;
            probe_total = &g_probe_stats.contains_probes;
            break;
        case RT_TRACKED_SET_PROBE_REMOVE:
            call_count = &g_probe_stats.remove_calls;
            probe_total = &g_probe_stats.remove_probes;
            break;
        default:
            return;
    }

    *call_count = rt_saturating_add_u64(*call_count, 1u);
    *probe_total = rt_saturating_add_u64(*probe_total, probes);
    if (probes > g_probe_stats.max_probe_depth) {
        g_probe_stats.max_probe_depth = probes;
    }
}


static inline void rt_tracked_set_record_maintenance(RtTrackedSetRebuildReason reason) {
    if (!g_probe_stats_enabled) {
        return;
    }

    g_probe_stats.maintenance_calls = rt_saturating_add_u64(g_probe_stats.maintenance_calls, 1u);
    if (reason == RT_TRACKED_SET_REBUILD_COMPACT_TOMBSTONES) {
        g_probe_stats.tombstone_compactions = rt_saturating_add_u64(g_probe_stats.tombstone_compactions, 1u);
    }
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


static void rt_tracked_set_ensure_scratch_capacity(uint64_t required_capacity) {
    if (g_tracked_set_scratch_capacity >= required_capacity) {
        return;
    }

    RtObjHeader** scratch = (RtObjHeader**)calloc((size_t)required_capacity, sizeof(RtObjHeader*));
    if (scratch == NULL) {
        rt_panic_oom();
    }

    free(g_tracked_set_scratch_slots);
    g_tracked_set_scratch_slots = scratch;
    g_tracked_set_scratch_capacity = required_capacity;
}


static void rt_tracked_set_rehash_live_entries(RtObjHeader** destination_slots, uint64_t destination_capacity) {
    for (uint64_t index = 0u; index < g_tracked_set_capacity; index++) {
        RtObjHeader* obj = g_tracked_set_slots[index];
        if (obj == NULL || obj == RT_TRACKED_SET_TOMBSTONE) {
            continue;
        }
        rt_insert_into_slots(destination_slots, destination_capacity, obj);
    }
}


static void rt_tracked_set_rebuild(uint64_t new_capacity, RtTrackedSetRebuildReason reason) {
    if (new_capacity < RT_TRACKED_SET_INITIAL_CAPACITY) {
        new_capacity = RT_TRACKED_SET_INITIAL_CAPACITY;
    }

    RtObjHeader** new_slots = (RtObjHeader**)calloc((size_t)new_capacity, sizeof(RtObjHeader*));
    if (new_slots == NULL) {
        rt_panic_oom();
    }

    rt_tracked_set_rehash_live_entries(new_slots, new_capacity);

    free(g_tracked_set_slots);
    g_tracked_set_slots = new_slots;
    g_tracked_set_capacity = new_capacity;
    g_tracked_set_occupied = g_tracked_set_size;
    rt_tracked_set_record_maintenance(reason);
}


static int rt_tracked_set_should_compact_tombstones(void) {
    if (g_tracked_set_capacity == 0u) {
        return 0;
    }

    uint64_t tombstones = rt_tracked_set_tombstone_count();
    if (tombstones == 0u) {
        return 0;
    }

    uint64_t minimum_tombstones = g_tracked_set_capacity / RT_TRACKED_SET_TOMBSTONE_COMPACT_DEN;
    if (minimum_tombstones == 0u) {
        minimum_tombstones = 1u;
    }

    return tombstones >= minimum_tombstones && tombstones >= (g_tracked_set_size * 2u);
}


static void rt_tracked_set_compact_tombstones(void) {
    rt_tracked_set_ensure_scratch_capacity(g_tracked_set_capacity);
    memset(g_tracked_set_scratch_slots, 0, (size_t)g_tracked_set_capacity * sizeof(RtObjHeader*));
    rt_tracked_set_rehash_live_entries(g_tracked_set_scratch_slots, g_tracked_set_capacity);

    RtObjHeader** old_slots = g_tracked_set_slots;
    g_tracked_set_slots = g_tracked_set_scratch_slots;
    g_tracked_set_scratch_slots = old_slots;

    g_tracked_set_occupied = g_tracked_set_size;
    rt_tracked_set_record_maintenance(RT_TRACKED_SET_REBUILD_COMPACT_TOMBSTONES);
}


static void rt_tracked_set_ensure_capacity_for_insert(void) {
    if (g_tracked_set_capacity == 0u) {
        rt_tracked_set_rebuild(RT_TRACKED_SET_INITIAL_CAPACITY, RT_TRACKED_SET_REBUILD_INITIALIZE);
        return;
    }

    uint64_t threshold = (g_tracked_set_capacity * RT_TRACKED_SET_LOAD_NUM) / RT_TRACKED_SET_LOAD_DEN;
    if (g_tracked_set_size + 1u > threshold) {
        rt_tracked_set_rebuild(g_tracked_set_capacity * 2u, RT_TRACKED_SET_REBUILD_GROW);
        return;
    }

    if (rt_tracked_set_should_compact_tombstones()) {
        rt_tracked_set_compact_tombstones();
        return;
    }

    if (g_tracked_set_occupied + 1u > threshold) {
        rt_tracked_set_rebuild(g_tracked_set_capacity, RT_TRACKED_SET_REBUILD_COMPACT_OCCUPANCY);
    }
}


static RtTrackedSetProbeResult rt_tracked_set_lookup_existing(const RtObjHeader* obj) {
    if (obj == NULL || g_tracked_set_capacity == 0u) {
        return rt_tracked_set_probe_result(UINT64_MAX, 0u, 0);
    }

    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    uint64_t probes = 0u;

    for (uint64_t step = 0u; step < g_tracked_set_capacity; step++) {
        probes++;
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            return rt_tracked_set_probe_result(UINT64_MAX, probes, 0);
        }
        if (slot == obj) {
            return rt_tracked_set_probe_result(index, probes, 1);
        }
        index = (index + 1u) & mask;
    }

    return rt_tracked_set_probe_result(UINT64_MAX, probes, 0);
}


static RtTrackedSetProbeResult rt_tracked_set_find_insertion_slot(const RtObjHeader* obj) {
    if (obj == NULL || g_tracked_set_capacity == 0u) {
        return rt_tracked_set_probe_result(UINT64_MAX, 0u, 0);
    }

    uint64_t mask = g_tracked_set_capacity - 1u;
    uint64_t index = rt_hash_ptr_uint64((uintptr_t)obj) & mask;
    uint64_t first_tombstone = UINT64_MAX;
    uint64_t probes = 0u;

    for (uint64_t step = 0u; step < g_tracked_set_capacity; step++) {
        probes++;
        RtObjHeader* slot = g_tracked_set_slots[index];
        if (slot == NULL) {
            uint64_t slot_index = (first_tombstone != UINT64_MAX) ? first_tombstone : index;
            return rt_tracked_set_probe_result(slot_index, probes, 0);
        }
        if (slot == RT_TRACKED_SET_TOMBSTONE) {
            if (first_tombstone == UINT64_MAX) {
                first_tombstone = index;
            }
        } else if (slot == obj) {
            return rt_tracked_set_probe_result(index, probes, 1);
        }
        index = (index + 1u) & mask;
    }

    return rt_tracked_set_probe_result(first_tombstone, probes, 0);
}


void rt_gc_tracked_set_insert(RtObjHeader* obj) {
    if (obj == NULL) {
        return;
    }

    rt_tracked_set_ensure_capacity_for_insert();

    RtTrackedSetProbeResult result = rt_tracked_set_find_insertion_slot(obj);
    rt_tracked_set_record_probe(RT_TRACKED_SET_PROBE_INSERT, result.probes);
    if (result.found || result.index == UINT64_MAX) {
        return;
    }

    if (g_tracked_set_slots[result.index] == NULL) {
        g_tracked_set_occupied++;
    }
    g_tracked_set_slots[result.index] = obj;
    g_tracked_set_size++;
}


int rt_gc_tracked_set_contains(const RtObjHeader* obj) {
    RtTrackedSetProbeResult result = rt_tracked_set_lookup_existing(obj);
    rt_tracked_set_record_probe(RT_TRACKED_SET_PROBE_CONTAINS, result.probes);
    return result.found;
}


void rt_gc_tracked_set_remove(RtObjHeader* obj) {
    RtTrackedSetProbeResult result = rt_tracked_set_lookup_existing(obj);
    rt_tracked_set_record_probe(RT_TRACKED_SET_PROBE_REMOVE, result.probes);
    if (!result.found || result.index == UINT64_MAX) {
        return;
    }

    g_tracked_set_slots[result.index] = RT_TRACKED_SET_TOMBSTONE;
    if (g_tracked_set_size > 0u) {
        g_tracked_set_size--;
    }
}


void rt_gc_tracked_set_reset(void) {
    free(g_tracked_set_slots);
    free(g_tracked_set_scratch_slots);
    g_tracked_set_slots = NULL;
    g_tracked_set_scratch_slots = NULL;
    g_tracked_set_capacity = 0u;
    g_tracked_set_scratch_capacity = 0u;
    g_tracked_set_size = 0u;
    g_tracked_set_occupied = 0u;
}


void rt_gc_tracked_set_enable_probe_stats(int enabled) {
    g_probe_stats_enabled = (enabled != 0);
}


RtGcTrackedSetProbeStats rt_gc_tracked_set_get_probe_stats(void) {
    return g_probe_stats;
}


void rt_gc_tracked_set_reset_probe_stats(void) {
    g_probe_stats = (RtGcTrackedSetProbeStats){0};
}
