#ifndef NIFLHEIM_RUNTIME_H
#define NIFLHEIM_RUNTIME_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtType RtType;
typedef struct RtObjHeader RtObjHeader;
typedef struct RtRootFrame RtRootFrame;
typedef struct RtThreadState RtThreadState;

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
};

typedef struct RtGcStats {
    uint64_t allocated_bytes;
    uint64_t live_bytes;
    uint64_t next_gc_threshold;
    uint64_t tracked_object_count;
} RtGcStats;

void rt_init(void);
void rt_shutdown(void);
RtThreadState* rt_thread_state(void);

void rt_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count);
void rt_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref);
void* rt_root_slot_load(const RtRootFrame* frame, uint32_t slot_index);

void rt_push_roots(RtThreadState* ts, RtRootFrame* frame);
void rt_pop_roots(RtThreadState* ts);

void rt_gc_register_global_root(void** slot);
void rt_gc_unregister_global_root(void** slot);

void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes);
RtGcStats rt_gc_get_stats(void);
void rt_gc_collect(RtThreadState* ts);
void* rt_str_from_bytes(RtThreadState* ts, const uint8_t* bytes, uint64_t len);
uint64_t rt_str_len(const void* str_obj);
uint64_t rt_str_get_u8(const void* str_obj, uint64_t index);
void* rt_box_i64_new(int64_t value);
void* rt_box_u64_new(uint64_t value);
void* rt_box_u8_new(uint64_t value);
void* rt_box_bool_new(int64_t value);
void* rt_box_double_new(double value);
int64_t rt_box_i64_get(const void* box_obj);
uint64_t rt_box_u64_get(const void* box_obj);
uint64_t rt_box_u8_get(const void* box_obj);
int64_t rt_box_bool_get(const void* box_obj);
double rt_box_double_get(const void* box_obj);
void rt_println_i64(int64_t value);
void rt_println_u64(uint64_t value);
void rt_println_u8(uint64_t value);
void rt_println_bool(int64_t value);
void* rt_checked_cast(void* obj, const RtType* expected_type);

__attribute__((noreturn)) void rt_panic(const char* message);
__attribute__((noreturn)) void rt_panic_null_deref(void);
__attribute__((noreturn)) void rt_panic_bad_cast(const char* from_type, const char* to_type);
__attribute__((noreturn)) void rt_panic_oom(void);

#ifdef __cplusplus
}
#endif

#endif
