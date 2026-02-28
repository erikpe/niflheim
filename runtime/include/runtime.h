#ifndef NIFLHEIM_RUNTIME_H
#define NIFLHEIM_RUNTIME_H

#include <stdint.h>

#include "array.h"
#include "gc.h"
#include "io.h"
#include "panic.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtType RtType;
typedef struct RtObjHeader RtObjHeader;
typedef struct RtRootFrame RtRootFrame;
typedef struct RtThreadState RtThreadState;
typedef struct RtTraceFrame RtTraceFrame;

enum {
    RT_GC_FLAG_MARKED = 1u << 0,
    RT_GC_FLAG_PINNED = 1u << 1,
};

enum {
    RT_TYPE_FLAG_HAS_REFS = 1u << 0,
    RT_TYPE_FLAG_VARIABLE_SIZE = 1u << 1,
    RT_TYPE_FLAG_LEAF = 1u << 2,
};

struct RtObjHeader {
    const RtType* type;
    uint64_t size_bytes;
    uint32_t gc_flags;
    uint32_t reserved0;
};

struct RtType {
    uint32_t type_id;
    uint32_t flags;
    uint32_t abi_version;
    uint32_t align_bytes;
    uint64_t fixed_size_bytes;
    const char* debug_name;
    void (*trace_fn)(void* obj, void (*mark_ref)(void** slot));
    const uint32_t* pointer_offsets;
    uint32_t pointer_offsets_count;
    uint32_t reserved0;
};

struct RtRootFrame {
    RtRootFrame* prev;
    uint32_t slot_count;
    uint32_t reserved;
    void** slots;
};

struct RtThreadState {
    RtRootFrame* roots_top;
    RtTraceFrame* trace_top;
};

struct RtTraceFrame {
    RtTraceFrame* prev;
    const char* function_name;
    const char* file_path;
    uint32_t line;
    uint32_t column;
};

void rt_init(void);
void rt_shutdown(void);
RtThreadState* rt_thread_state(void);

void rt_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count);
void rt_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref);
void* rt_root_slot_load(const RtRootFrame* frame, uint32_t slot_index);

void rt_push_roots(RtThreadState* ts, RtRootFrame* frame);
void rt_pop_roots(RtThreadState* ts);

void rt_trace_push(const char* function_name, const char* file_path, uint32_t line, uint32_t column);
void rt_trace_pop(void);
void rt_trace_set_location(uint32_t line, uint32_t column);

void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes);
void* rt_checked_cast(void* obj, const RtType* expected_type);

#ifdef __cplusplus
}
#endif

#endif
