#ifndef NIFLHEIM_RUNTIME_GC_H
#define NIFLHEIM_RUNTIME_GC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtObjHeader RtObjHeader;

enum {
    RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT = 7u,
};

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
    uint64_t tracked_set_active;
} RtGcStats;

typedef struct RtGcTrackingPoolStats {
    uint64_t allocation_requests;
    uint64_t pool_hits;
    uint64_t pool_misses;
    uint64_t chunk_allocations;
    uint64_t nodes_returned;
    uint64_t available_nodes;
} RtGcTrackingPoolStats;

typedef struct RtSmallObjectFreelistBucketStats {
    uint64_t object_size_bytes;
    uint64_t allocation_requests;
    uint64_t freelist_hits;
    uint64_t freelist_misses;
    uint64_t returned_objects;
    uint64_t retained_objects;
} RtSmallObjectFreelistBucketStats;

typedef struct RtSmallObjectFreelistStats {
    uint64_t bucket_count;
    uint64_t eligible_requests;
    uint64_t variable_size_requests;
    uint64_t unsupported_size_requests;
    uint64_t fallback_allocations;
    RtSmallObjectFreelistBucketStats buckets[RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT];
} RtSmallObjectFreelistStats;

void rt_gc_register_global_root(void** slot);
void rt_gc_unregister_global_root(void** slot);

RtGcStats rt_gc_get_stats(void);
RtGcTrackingPoolStats rt_gc_get_tracking_pool_stats(void);
RtSmallObjectFreelistStats rt_gc_get_small_object_freelist_stats(void);
void rt_gc_collect(void);

void rt_gc_maybe_collect(uint64_t upcoming_bytes);
void rt_gc_track_allocation(RtObjHeader* obj);
void rt_gc_reset_tracking_pool_stats(void);
void rt_gc_reset_small_object_freelist_stats(void);
void rt_gc_reset_state(void);

#ifdef __cplusplus
}
#endif

#endif
