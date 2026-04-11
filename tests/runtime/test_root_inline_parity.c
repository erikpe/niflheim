#include "runtime_dbg.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static void fail(const char* message) {
    fprintf(stderr, "test_root_inline_parity: %s\n", message);
    exit(1);
}


static void assert_true(int condition, const char* message) {
    if (!condition) {
        fail(message);
    }
}


static void inline_root_frame_init(RtRootFrame* frame, void** slots, uint32_t slot_count) {
    frame->prev = NULL;
    frame->slot_count = slot_count;
    frame->reserved = 0;
    frame->slots = slots;
    for (uint32_t i = 0; i < slot_count; i++) {
        slots[i] = NULL;
    }
}


static void inline_root_slot_store(RtRootFrame* frame, uint32_t slot_index, void* ref) {
    frame->slots[slot_index] = ref;
}


static void* inline_root_slot_load(const RtRootFrame* frame, uint32_t slot_index) {
    return frame->slots[slot_index];
}


static void inline_push_roots(RtThreadState* ts, RtRootFrame* frame) {
    frame->prev = ts->roots_top;
    ts->roots_top = frame;
}


static void inline_pop_roots(RtThreadState* ts) {
    RtRootFrame* top = ts->roots_top;
    ts->roots_top = top->prev;
}


static void assert_frame_shape_matches(
    const RtRootFrame* helper_frame,
    const RtRootFrame* inline_frame,
    void* const* helper_slots,
    void* const* inline_slots,
    uint32_t slot_count
) {
    assert_true(helper_frame->slot_count == inline_frame->slot_count, "slot_count should match");
    assert_true(helper_frame->reserved == inline_frame->reserved, "reserved should match");
    assert_true(helper_frame->prev == NULL, "helper frame prev should be NULL before push");
    assert_true(inline_frame->prev == NULL, "inline frame prev should be NULL before push");
    assert_true(helper_frame->slots == helper_slots, "helper frame slots pointer should match helper storage");
    assert_true(inline_frame->slots == inline_slots, "inline frame slots pointer should match inline storage");
    for (uint32_t i = 0; i < slot_count; i++) {
        assert_true(helper_slots[i] == inline_slots[i], "slot contents should match");
    }
}


static void test_init_and_slot_access_match_inline_path(void) {
    RtRootFrame helper_frame;
    RtRootFrame inline_frame;
    void* helper_slots[3] = {(void*)(uintptr_t)1u, (void*)(uintptr_t)2u, (void*)(uintptr_t)3u};
    void* inline_slots[3] = {(void*)(uintptr_t)4u, (void*)(uintptr_t)5u, (void*)(uintptr_t)6u};
    int value_a = 11;
    int value_b = 22;

    rt_dbg_root_frame_init(&helper_frame, helper_slots, 3u);
    inline_root_frame_init(&inline_frame, inline_slots, 3u);
    assert_frame_shape_matches(&helper_frame, &inline_frame, helper_slots, inline_slots, 3u);

    rt_dbg_root_slot_store(&helper_frame, 0u, &value_a);
    rt_dbg_root_slot_store(&helper_frame, 2u, &value_b);
    inline_root_slot_store(&inline_frame, 0u, &value_a);
    inline_root_slot_store(&inline_frame, 2u, &value_b);

    assert_true(rt_dbg_root_slot_load(&helper_frame, 0u) == inline_root_slot_load(&inline_frame, 0u), "slot 0 load should match inline path");
    assert_true(rt_dbg_root_slot_load(&helper_frame, 1u) == inline_root_slot_load(&inline_frame, 1u), "slot 1 load should match inline path");
    assert_true(rt_dbg_root_slot_load(&helper_frame, 2u) == inline_root_slot_load(&inline_frame, 2u), "slot 2 load should match inline path");
}


static void test_single_push_and_pop_match_inline_path(void) {
    RtThreadState helper_ts = {0};
    RtThreadState inline_ts = {0};
    RtRootFrame helper_prev = {0};
    RtRootFrame inline_prev = {0};
    RtRootFrame helper_frame;
    RtRootFrame inline_frame;
    void* helper_slots[1] = {NULL};
    void* inline_slots[1] = {NULL};

    helper_ts.roots_top = &helper_prev;
    inline_ts.roots_top = &inline_prev;
    rt_dbg_root_frame_init(&helper_frame, helper_slots, 1u);
    inline_root_frame_init(&inline_frame, inline_slots, 1u);

    rt_dbg_push_roots(&helper_ts, &helper_frame);
    inline_push_roots(&inline_ts, &inline_frame);

    assert_true(helper_ts.roots_top == &helper_frame, "helper push should publish frame");
    assert_true(inline_ts.roots_top == &inline_frame, "inline push should publish frame");
    assert_true(helper_frame.prev == &helper_prev, "helper push should link previous top");
    assert_true(inline_frame.prev == &inline_prev, "inline push should link previous top");

    rt_dbg_pop_roots(&helper_ts);
    inline_pop_roots(&inline_ts);

    assert_true(helper_ts.roots_top == &helper_prev, "helper pop should restore previous top");
    assert_true(inline_ts.roots_top == &inline_prev, "inline pop should restore previous top");
}


static void test_nested_push_and_pop_match_inline_path(void) {
    RtThreadState helper_ts = {0};
    RtThreadState inline_ts = {0};
    RtRootFrame helper_outer;
    RtRootFrame helper_inner;
    RtRootFrame inline_outer;
    RtRootFrame inline_inner;
    void* helper_outer_slots[1] = {NULL};
    void* helper_inner_slots[1] = {NULL};
    void* inline_outer_slots[1] = {NULL};
    void* inline_inner_slots[1] = {NULL};

    rt_dbg_root_frame_init(&helper_outer, helper_outer_slots, 1u);
    rt_dbg_root_frame_init(&helper_inner, helper_inner_slots, 1u);
    inline_root_frame_init(&inline_outer, inline_outer_slots, 1u);
    inline_root_frame_init(&inline_inner, inline_inner_slots, 1u);

    rt_dbg_push_roots(&helper_ts, &helper_outer);
    inline_push_roots(&inline_ts, &inline_outer);
    assert_true(helper_ts.roots_top == &helper_outer, "helper outer frame should be top after first push");
    assert_true(inline_ts.roots_top == &inline_outer, "inline outer frame should be top after first push");

    rt_dbg_push_roots(&helper_ts, &helper_inner);
    inline_push_roots(&inline_ts, &inline_inner);
    assert_true(helper_ts.roots_top == &helper_inner, "helper inner frame should be top after nested push");
    assert_true(inline_ts.roots_top == &inline_inner, "inline inner frame should be top after nested push");
    assert_true(helper_inner.prev == &helper_outer, "helper nested push should chain to outer frame");
    assert_true(inline_inner.prev == &inline_outer, "inline nested push should chain to outer frame");

    rt_dbg_pop_roots(&helper_ts);
    inline_pop_roots(&inline_ts);
    assert_true(helper_ts.roots_top == &helper_outer, "helper pop should restore outer frame");
    assert_true(inline_ts.roots_top == &inline_outer, "inline pop should restore outer frame");

    rt_dbg_pop_roots(&helper_ts);
    inline_pop_roots(&inline_ts);
    assert_true(helper_ts.roots_top == NULL, "helper final pop should clear roots_top");
    assert_true(inline_ts.roots_top == NULL, "inline final pop should clear roots_top");
}


int main(void) {
    test_init_and_slot_access_match_inline_path();
    test_single_push_and_pop_match_inline_path();
    test_nested_push_and_pop_match_inline_path();

    puts("test_root_inline_parity: ok");
    return 0;
}