#ifndef TOY_RUNTIME_H
#define TOY_RUNTIME_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtType RtType;
typedef struct RtObjHeader RtObjHeader;
typedef struct RtRootFrame RtRootFrame;
typedef struct RtThreadState RtThreadState;

struct RtObjHeader {
    uint32_t type_id;
    uint32_t gc_flags;
    uint64_t size_bytes;
    const RtType* type;
};

struct RtType {
    uint32_t type_id;
    uint32_t flags;
    const char* debug_name;
    void (*trace_fn)(void* obj, void (*mark_ref)(void** slot));
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

void rt_init(void);
void rt_shutdown(void);
RtThreadState* rt_thread_state(void);
void rt_push_roots(RtThreadState* ts, RtRootFrame* frame);
void rt_pop_roots(RtThreadState* ts);
void* rt_alloc_obj(RtThreadState* ts, const RtType* type, uint64_t payload_bytes);
void rt_gc_collect(RtThreadState* ts);

__attribute__((noreturn)) void rt_panic(const char* message);

#ifdef __cplusplus
}
#endif

#endif
