#include "runtime_dbg.h"

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
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
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
    rt_dbg_root_frame_init(&frame, slots, 2);
    rt_dbg_push_roots(rt_thread_state(), &frame);

    if (rt_dbg_root_slot_load(&frame, 0) != NULL || rt_dbg_root_slot_load(&frame, 1) != NULL) {
        fail("newly initialized slots must start as NULL");
    }

    LeafObj* a = alloc_leaf(123);
    LeafObj* b = alloc_leaf(456);

    rt_dbg_root_slot_store(&frame, 0, a);
    rt_dbg_root_slot_store(&frame, 1, b);

    if (rt_dbg_root_slot_load(&frame, 0) != (void*)a) {
        fail("slot 0 should return stored pointer");
    }
    if (rt_dbg_root_slot_load(&frame, 1) != (void*)b) {
        fail("slot 1 should return stored pointer");
    }

    rt_gc_collect();
    RtGcStats alive = rt_gc_get_stats();
    if (alive.tracked_object_count < 2) {
        fail("rooted objects should remain alive across collection");
    }

    rt_dbg_root_slot_store(&frame, 0, NULL);
    rt_dbg_root_slot_store(&frame, 1, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats cleared = rt_gc_get_stats();
    if (cleared.tracked_object_count != 0) {
        fail("cleared and popped frame should allow reclamation");
    }
}


static void test_nested_root_frames_pop_in_lifo_order(void) {
    void* outer_slots[1] = {NULL};
    void* inner_slots[1] = {NULL};
    RtRootFrame outer_frame;
    RtRootFrame inner_frame;

    rt_dbg_root_frame_init(&outer_frame, outer_slots, 1);
    rt_dbg_push_roots(rt_thread_state(), &outer_frame);
    rt_dbg_root_frame_init(&inner_frame, inner_slots, 1);
    rt_dbg_push_roots(rt_thread_state(), &inner_frame);

    LeafObj* outer = alloc_leaf(1001);
    LeafObj* inner = alloc_leaf(2002);
    rt_dbg_root_slot_store(&outer_frame, 0, outer);
    rt_dbg_root_slot_store(&inner_frame, 0, inner);

    if (rt_thread_state()->roots_top != &inner_frame) {
        fail("inner frame should become the shadow-stack top after push");
    }

    rt_gc_collect();
    RtGcStats both_alive = rt_gc_get_stats();
    if (both_alive.tracked_object_count < 2) {
        fail("nested root frames should keep both objects alive");
    }

    rt_dbg_pop_roots(rt_thread_state());
    if (rt_thread_state()->roots_top != &outer_frame) {
        fail("popping inner frame should restore the outer frame as top");
    }

    rt_gc_collect();
    RtGcStats only_outer_alive = rt_gc_get_stats();
    if (only_outer_alive.tracked_object_count != 1) {
        fail("popped inner frame should stop keeping its object alive");
    }
    if (rt_dbg_root_slot_load(&outer_frame, 0) != (void*)outer) {
        fail("outer frame should still retain its rooted object after inner pop");
    }

    rt_dbg_root_slot_store(&outer_frame, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());
    if (rt_thread_state()->roots_top != NULL) {
        fail("popping the last frame should clear the shadow-stack top");
    }

    rt_gc_collect();
    RtGcStats none_alive = rt_gc_get_stats();
    if (none_alive.tracked_object_count != 0) {
        fail("all objects should be reclaimable after all frames are popped");
    }
}


static void test_global_root_basic_roundtrip(void) {
    void* global_slot = NULL;
    rt_gc_register_global_root(&global_slot);

    global_slot = alloc_leaf(777);
    rt_gc_collect();
    RtGcStats alive = rt_gc_get_stats();
    if (alive.tracked_object_count != 1) {
        fail("registered global root should keep object alive");
    }

    global_slot = NULL;
    rt_gc_unregister_global_root(&global_slot);
    rt_gc_collect();

    RtGcStats cleared = rt_gc_get_stats();
    if (cleared.tracked_object_count != 0) {
        fail("unregistered global root should not keep object alive");
    }
}


int main(void) {
    rt_init();

    test_root_slots_basic_roundtrip();
    test_nested_root_frames_pop_in_lifo_order();
    test_global_root_basic_roundtrip();

    rt_shutdown();
    puts("test_roots_positive: ok");
    return 0;
}
