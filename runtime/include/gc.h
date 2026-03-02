#ifndef NIFLHEIM_RUNTIME_GC_H
#define NIFLHEIM_RUNTIME_GC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtThreadState RtThreadState;
typedef struct RtObjHeader RtObjHeader;

typedef struct RtGcStats {
    uint64_t allocated_bytes;
    uint64_t live_bytes;
    uint64_t next_gc_threshold;
    uint64_t tracked_object_count;
} RtGcStats;

void rt_gc_register_global_root(void** slot);
void rt_gc_unregister_global_root(void** slot);

RtGcStats rt_gc_get_stats(void);
void rt_gc_collect(RtThreadState* ts);

void rt_gc_maybe_collect(RtThreadState* ts, uint64_t upcoming_bytes);
void rt_gc_track_allocation(RtObjHeader* obj);
void rt_gc_reset_state(void);

#ifdef __cplusplus
}
#endif

#endif