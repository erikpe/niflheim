#ifndef NIFLHEIM_RUNTIME_DBG_H
#define NIFLHEIM_RUNTIME_DBG_H

#include "runtime.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Debug/test-only shadow-stack helpers.
 * Compiler-generated code manipulates RtRootFrame and RtThreadState inline and
 * does not depend on these symbols. */
void rt_dbg_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count);
void rt_dbg_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref);
void* rt_dbg_root_slot_load(const RtRootFrame* frame, uint32_t slot_index);

void rt_dbg_push_roots(RtThreadState* ts, RtRootFrame* frame);
void rt_dbg_pop_roots(RtThreadState* ts);

#ifdef __cplusplus
}
#endif

#endif