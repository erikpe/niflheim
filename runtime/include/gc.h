#ifndef NIFLHEIM_RUNTIME_GC_H
#define NIFLHEIM_RUNTIME_GC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtObjHeader RtObjHeader;

#ifndef NIF_GC_VALIDATE_TRACKED_SET
#define NIF_GC_VALIDATE_TRACKED_SET 0
#endif

#if NIF_GC_VALIDATE_TRACKED_SET != 0 && NIF_GC_VALIDATE_TRACKED_SET != 1
#error "NIF_GC_VALIDATE_TRACKED_SET must be 0 or 1"
#endif

typedef struct RtGcStats {
    uint64_t allocated_bytes;
    uint64_t live_bytes;
    uint64_t next_gc_threshold;
    uint64_t tracked_object_count;
    uint64_t tracked_set_validation_enabled;
} RtGcStats;

typedef struct RtGcTrackingPoolStats {
    uint64_t allocation_requests;
    uint64_t pool_hits;
    uint64_t pool_misses;
    uint64_t chunk_allocations;
    uint64_t nodes_returned;
    uint64_t available_nodes;
} RtGcTrackingPoolStats;

void rt_gc_register_global_root(void** slot);
void rt_gc_unregister_global_root(void** slot);

RtGcStats rt_gc_get_stats(void);
RtGcTrackingPoolStats rt_gc_get_tracking_pool_stats(void);
void rt_gc_collect(void);

void rt_gc_maybe_collect(uint64_t upcoming_bytes);
void rt_gc_track_allocation(RtObjHeader* obj);
void rt_gc_reset_tracking_pool_stats(void);
void rt_gc_reset_state(void);

#ifdef __cplusplus
}
#endif

#endif
