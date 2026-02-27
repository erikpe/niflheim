#include "runtime.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct LeafObj {
    RtObjHeader header;
    uint64_t value;
} LeafObj;


static const RtType LEAF_TYPE = {
    .type_id = 0x4C454146u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(LeafObj),
    .debug_name = "Leaf",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};


static void fail(const char* message) {
    fprintf(stderr, "test_array_runtime: %s\n", message);
    exit(1);
}

static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(stderr, "test_array_runtime: %s (actual=%llu expected=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)expected);
        exit(1);
    }
}

static void assert_true(int condition, const char* message) {
    if (!condition) {
        fail(message);
    }
}

static LeafObj* alloc_leaf(uint64_t value) {
    uint64_t payload = sizeof(LeafObj) - sizeof(RtObjHeader);
    LeafObj* leaf = (LeafObj*)rt_alloc_obj(rt_thread_state(), &LEAF_TYPE, payload);
    leaf->value = value;
    return leaf;
}

static void test_u8_array_basics_and_slice_copy(void) {
    void* arr = rt_array_new_u8(4u);
    assert_u64_eq(rt_array_len(arr), 4u, "u8[] len should match constructor");
    assert_u64_eq(rt_array_get_u8(arr, 0u), 0u, "u8[] should default initialize to zero");

    rt_array_set_u8(arr, 0u, 9u);
    rt_array_set_u8(arr, 1u, 7u);
    assert_u64_eq(rt_array_get_u8(arr, 0u), 9u, "u8[] set/get should round-trip");
    assert_u64_eq(rt_array_get_u8(arr, 1u), 7u, "u8[] second value should round-trip");

    void* slice = rt_array_slice_u8(arr, 0u, 2u);
    assert_u64_eq(rt_array_len(slice), 2u, "u8[] slice len should match range");
    assert_u64_eq(rt_array_get_u8(slice, 0u), 9u, "u8[] slice should copy first element");
    assert_u64_eq(rt_array_get_u8(slice, 1u), 7u, "u8[] slice should copy second element");

    rt_array_set_u8(arr, 0u, 1u);
    assert_u64_eq(rt_array_get_u8(slice, 0u), 9u, "u8[] slice must be independent copy");
}

static void test_ref_array_gc_tracing(void) {
    RtThreadState* ts = rt_thread_state();
    RtRootFrame frame;
    void* slots[1] = {NULL};
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(ts, &frame);

    void* arr = rt_array_new_ref(2u);
    rt_root_slot_store(&frame, 0, arr);

    LeafObj* a = alloc_leaf(1u);
    LeafObj* b = alloc_leaf(2u);
    rt_array_set_ref(arr, 0u, a);
    rt_array_set_ref(arr, 1u, b);

    rt_gc_collect(ts);
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 3u, "rooted ref array should keep element refs alive");

    rt_array_set_ref(arr, 1u, NULL);
    rt_gc_collect(ts);
    RtGcStats one_cleared = rt_gc_get_stats();
    assert_u64_eq(one_cleared.tracked_object_count, 2u, "clearing one ref slot should reclaim one element");

    rt_array_set_ref(arr, 0u, NULL);
    rt_gc_collect(ts);
    RtGcStats all_cleared = rt_gc_get_stats();
    assert_u64_eq(all_cleared.tracked_object_count, 1u, "clearing all ref slots should keep only array alive");

    rt_root_slot_store(&frame, 0, NULL);
    rt_pop_roots(ts);
    rt_gc_collect(ts);
    RtGcStats none_alive = rt_gc_get_stats();
    assert_u64_eq(none_alive.tracked_object_count, 0u, "dropping root should reclaim array");
}

static void test_ref_slice_copy_independence(void) {
    RtThreadState* ts = rt_thread_state();
    RtRootFrame frame;
    void* slots[2] = {NULL, NULL};
    rt_root_frame_init(&frame, slots, 2);
    rt_push_roots(ts, &frame);

    void* arr = rt_array_new_ref(2u);
    rt_root_slot_store(&frame, 0, arr);

    LeafObj* a = alloc_leaf(10u);
    LeafObj* b = alloc_leaf(20u);
    rt_array_set_ref(arr, 0u, a);
    rt_array_set_ref(arr, 1u, b);

    void* slice = rt_array_slice_ref(arr, 0u, 2u);
    rt_root_slot_store(&frame, 1, slice);

    assert_true(rt_array_get_ref(slice, 0u) == (void*)a, "ref[] slice should copy slot 0");
    assert_true(rt_array_get_ref(slice, 1u) == (void*)b, "ref[] slice should copy slot 1");

    rt_array_set_ref(arr, 0u, NULL);
    assert_true(rt_array_get_ref(slice, 0u) == (void*)a, "ref[] slice should not alias source slots");

    rt_root_slot_store(&frame, 0, NULL);
    rt_root_slot_store(&frame, 1, NULL);
    rt_pop_roots(ts);
    rt_gc_collect(ts);
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0u, "all objects should reclaim after clearing roots");
}

int main(void) {
    rt_init();

    test_u8_array_basics_and_slice_copy();
    test_ref_array_gc_tracing();
    test_ref_slice_copy_independence();

    rt_shutdown();
    puts("test_array_runtime: ok");
    return 0;
}
