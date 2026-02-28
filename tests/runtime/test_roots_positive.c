#include "runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct LeafObj {
    RtObjHeader header;
    uint64_t value;
} LeafObj;


static const RtType LEAF_TYPE = {
    .type_id = 11,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(LeafObj),
    .debug_name = "LeafPositive",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
};


static void fail(const char* message) {
    fprintf(stderr, "test_roots_positive: %s\n", message);
    exit(1);
}


static LeafObj* alloc_leaf(uint64_t value) {
    uint64_t payload = sizeof(LeafObj) - sizeof(RtObjHeader);
    LeafObj* leaf = (LeafObj*)rt_alloc_obj(rt_thread_state(), &LEAF_TYPE, payload);
    leaf->value = value;
    return leaf;
}


static void test_root_slots_basic_roundtrip(void) {
    void* slots[2] = {NULL, NULL};
    RtRootFrame frame;
    rt_root_frame_init(&frame, slots, 2);
    rt_push_roots(rt_thread_state(), &frame);

    if (rt_root_slot_load(&frame, 0) != NULL || rt_root_slot_load(&frame, 1) != NULL) {
        fail("newly initialized slots must start as NULL");
    }

    LeafObj* a = alloc_leaf(123);
    LeafObj* b = alloc_leaf(456);

    rt_root_slot_store(&frame, 0, a);
    rt_root_slot_store(&frame, 1, b);

    if (rt_root_slot_load(&frame, 0) != (void*)a) {
        fail("slot 0 should return stored pointer");
    }
    if (rt_root_slot_load(&frame, 1) != (void*)b) {
        fail("slot 1 should return stored pointer");
    }

    rt_gc_collect(rt_thread_state());
    RtGcStats alive = rt_gc_get_stats();
    if (alive.tracked_object_count < 2) {
        fail("rooted objects should remain alive across collection");
    }

    rt_root_slot_store(&frame, 0, NULL);
    rt_root_slot_store(&frame, 1, NULL);
    rt_pop_roots(rt_thread_state());

    rt_gc_collect(rt_thread_state());
    RtGcStats cleared = rt_gc_get_stats();
    if (cleared.tracked_object_count != 0) {
        fail("cleared and popped frame should allow reclamation");
    }
}


static void test_global_root_basic_roundtrip(void) {
    void* global_slot = NULL;
    rt_gc_register_global_root(&global_slot);

    global_slot = alloc_leaf(777);
    rt_gc_collect(rt_thread_state());
    RtGcStats alive = rt_gc_get_stats();
    if (alive.tracked_object_count != 1) {
        fail("registered global root should keep object alive");
    }

    global_slot = NULL;
    rt_gc_unregister_global_root(&global_slot);
    rt_gc_collect(rt_thread_state());

    RtGcStats cleared = rt_gc_get_stats();
    if (cleared.tracked_object_count != 0) {
        fail("unregistered global root should not keep object alive");
    }
}


int main(void) {
    rt_init();

    test_root_slots_basic_roundtrip();
    test_global_root_basic_roundtrip();

    rt_shutdown();
    puts("test_roots_positive: ok");
    return 0;
}
