#include "runtime_dbg.h"

#include <stddef.h>


static void rt_dbg_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}


static void rt_dbg_root_frame_bind(RtRootFrame* frame, void** slots, uint32_t slot_count) {
    frame->prev = NULL;
    frame->slot_count = slot_count;
    frame->reserved = 0;
    frame->slots = slots;
}


static void rt_dbg_root_frame_zero_slots(RtRootFrame* frame) {
    for (uint32_t i = 0; i < frame->slot_count; i++) {
        frame->slots[i] = NULL;
    }
}


static void rt_dbg_root_frame_publish(RtThreadState* ts, RtRootFrame* frame) {
    frame->prev = ts->roots_top;
    ts->roots_top = frame;
}


static RtRootFrame* rt_dbg_root_frame_unpublish(RtThreadState* ts) {
    RtRootFrame* top = ts->roots_top;
    ts->roots_top = top->prev;
    return top;
}


void rt_dbg_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count) {
    rt_dbg_require(frame != NULL, "rt_dbg_root_frame_init: frame is NULL");
    rt_dbg_require(slot_count == 0 || slots != NULL, "rt_dbg_root_frame_init: slots is NULL with non-zero slot_count");

    rt_dbg_root_frame_bind(frame, slots, slot_count);
    rt_dbg_root_frame_zero_slots(frame);
}


void rt_dbg_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref) {
    rt_dbg_require(frame != NULL, "rt_dbg_root_slot_store: frame is NULL");
    rt_dbg_require(slot_index < frame->slot_count, "rt_dbg_root_slot_store: slot index out of bounds");
    frame->slots[slot_index] = ref;
}


void* rt_dbg_root_slot_load(const RtRootFrame* frame, uint32_t slot_index) {
    rt_dbg_require(frame != NULL, "rt_dbg_root_slot_load: frame is NULL");
    rt_dbg_require(slot_index < frame->slot_count, "rt_dbg_root_slot_load: slot index out of bounds");
    return frame->slots[slot_index];
}


void rt_dbg_push_roots(RtThreadState* ts, RtRootFrame* frame) {
    rt_dbg_require(ts != NULL, "rt_dbg_push_roots: thread state is NULL");
    rt_dbg_require(frame != NULL, "rt_dbg_push_roots: frame is NULL");
    rt_dbg_require(frame->slot_count == 0 || frame->slots != NULL, "rt_dbg_push_roots: frame slots is NULL");

    rt_dbg_root_frame_publish(ts, frame);
}


void rt_dbg_pop_roots(RtThreadState* ts) {
    rt_dbg_require(ts != NULL, "rt_dbg_pop_roots: thread state is NULL");
    rt_dbg_require(ts->roots_top != NULL, "rt_dbg_pop_roots: shadow stack underflow");

    (void)rt_dbg_root_frame_unpublish(ts);
}