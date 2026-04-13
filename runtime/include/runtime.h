#ifndef NIFLHEIM_RUNTIME_H
#define NIFLHEIM_RUNTIME_H

#include <stdint.h>

#include "array.h"
#include "gc.h"
#include "io.h"
#include "math_rt.h"
#include "panic.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtType RtType;
typedef struct RtInterfaceType RtInterfaceType;
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

struct RtInterfaceType {
    const char* debug_name;
    uint32_t slot_index;
    uint32_t method_count;
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
    const RtType* super_type;
    const void* const* interface_tables;
    uint32_t interface_slot_count;
    uint32_t reserved1;
    const void* class_vtable;
    uint32_t class_vtable_count;
    uint32_t reserved2;
};

struct RtRootFrame {
    RtRootFrame* prev;
    uint32_t slot_count;
    uint32_t reserved;
    void** slots;
};

struct RtThreadState {
    RtRootFrame* roots_top;
    RtTraceFrame* trace_frames;
    uint32_t trace_size;
    uint32_t trace_capacity;
};

struct RtTraceFrame {
    const char* function_name;
    const char* file_path;
    uint32_t line;
    uint32_t column;
};

void rt_init(void);
void rt_shutdown(void);
RtThreadState* rt_thread_state(void);

void rt_trace_push(const char* function_name, const char* file_path, uint32_t line, uint32_t column);
void rt_trace_pop(void);
void rt_trace_set_location(uint32_t line, uint32_t column);

void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes);
void rt_panic_null_deref(void);
void* rt_checked_cast(void* obj, const RtType* expected_type);
double rt_cast_u64_to_double(uint64_t value);
int64_t rt_cast_double_to_i64(double value);
uint64_t rt_cast_double_to_u64(double value);
uint64_t rt_cast_double_to_u8(double value);
uint64_t rt_is_instance_of_type(void* obj, const RtType* expected_type);
uint64_t rt_obj_same_type(void* lhs, void* rhs);

#ifdef __cplusplus
}
#endif

#endif
