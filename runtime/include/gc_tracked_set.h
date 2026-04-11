#ifndef NIFLHEIM_RUNTIME_GC_TRACKED_SET_H
#define NIFLHEIM_RUNTIME_GC_TRACKED_SET_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtObjHeader RtObjHeader;

typedef struct RtGcTrackedSetProbeStats {
	uint64_t insert_calls;
	uint64_t contains_calls;
	uint64_t remove_calls;
	uint64_t insert_probes;
	uint64_t contains_probes;
	uint64_t remove_probes;
	uint64_t max_probe_depth;
	uint64_t maintenance_calls;
	uint64_t tombstone_compactions;
} RtGcTrackedSetProbeStats;

void rt_gc_tracked_set_insert(RtObjHeader* obj);
int rt_gc_tracked_set_contains(const RtObjHeader* obj);
void rt_gc_tracked_set_remove(RtObjHeader* obj);
void rt_gc_tracked_set_enable_probe_stats(int enabled);
RtGcTrackedSetProbeStats rt_gc_tracked_set_get_probe_stats(void);
void rt_gc_tracked_set_reset_probe_stats(void);
void rt_gc_tracked_set_reset(void);

#ifdef __cplusplus
}
#endif

#endif