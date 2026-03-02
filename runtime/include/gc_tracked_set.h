#ifndef NIFLHEIM_RUNTIME_GC_TRACKED_SET_H
#define NIFLHEIM_RUNTIME_GC_TRACKED_SET_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtObjHeader RtObjHeader;

void rt_gc_tracked_set_insert(RtObjHeader* obj);
int rt_gc_tracked_set_contains(const RtObjHeader* obj);
void rt_gc_tracked_set_remove(RtObjHeader* obj);
void rt_gc_tracked_set_reset(void);

#ifdef __cplusplus
}
#endif

#endif