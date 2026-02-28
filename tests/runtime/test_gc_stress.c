#include "runtime.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct NodeObj {
    RtObjHeader header;
    void* next;
} NodeObj;


typedef struct LeafObj {
    RtObjHeader header;
    uint64_t value;
} LeafObj;


static void* g_test_global_root = NULL;


static const uint32_t NODE_POINTER_OFFSETS[] = {
    (uint32_t)offsetof(NodeObj, next),
};


static const RtType NODE_TYPE = {
    .type_id = 1,
    .flags = RT_TYPE_FLAG_HAS_REFS,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(NodeObj),
    .debug_name = "Node",
    .trace_fn = NULL,
    .pointer_offsets = NODE_POINTER_OFFSETS,
    .pointer_offsets_count = 1,
    .reserved0 = 0,
};


static const RtType LEAF_TYPE = {
    .type_id = 2,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(LeafObj),
    .debug_name = "Leaf",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
};


static void fail(const char* message) {
    fprintf(stderr, "test_gc_stress: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(stderr, "test_gc_stress: %s (actual=%llu expected=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)expected);
        exit(1);
    }
}


static NodeObj* alloc_node(void) {
    uint64_t payload = sizeof(NodeObj) - sizeof(RtObjHeader);
    return (NodeObj*)rt_alloc_obj(rt_thread_state(), &NODE_TYPE, payload);
}


static LeafObj* alloc_leaf(uint64_t value) {
    uint64_t payload = sizeof(LeafObj) - sizeof(RtObjHeader);
    LeafObj* leaf = (LeafObj*)rt_alloc_obj(rt_thread_state(), &LEAF_TYPE, payload);
    leaf->value = value;
    return leaf;
}


static void test_no_roots_reclaim(void) {
    for (uint64_t i = 0; i < 200; i++) {
        alloc_leaf(i);
    }

    rt_gc_collect(rt_thread_state());
    RtGcStats stats = rt_gc_get_stats();
    assert_u64_eq(stats.tracked_object_count, 0, "no roots should reclaim all objects");
    assert_u64_eq(stats.live_bytes, 0, "no roots should leave zero live bytes");
}


static void test_rooted_chain_survives_then_reclaims(void) {
    void* slots[1] = {NULL};
    RtRootFrame frame;
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(rt_thread_state(), &frame);

    NodeObj* a = alloc_node();
    NodeObj* b = alloc_node();
    NodeObj* c = alloc_node();
    a->next = b;
    b->next = c;
    c->next = NULL;

    rt_root_slot_store(&frame, 0, a);

    rt_gc_collect(rt_thread_state());
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 3, "rooted chain should survive collection");

    rt_root_slot_store(&frame, 0, NULL);
    rt_pop_roots(rt_thread_state());

    rt_gc_collect(rt_thread_state());
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "cleared root should allow chain reclamation");
}


static void test_cycle_reachable_then_unreachable(void) {
    void* slots[1] = {NULL};
    RtRootFrame frame;
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(rt_thread_state(), &frame);

    NodeObj* n1 = alloc_node();
    NodeObj* n2 = alloc_node();
    n1->next = n2;
    n2->next = n1;

    rt_root_slot_store(&frame, 0, n1);
    rt_gc_collect(rt_thread_state());
    RtGcStats reachable = rt_gc_get_stats();
    assert_u64_eq(reachable.tracked_object_count, 2, "reachable cycle should survive");

    rt_root_slot_store(&frame, 0, NULL);
    rt_pop_roots(rt_thread_state());

    rt_gc_collect(rt_thread_state());
    RtGcStats unreachable = rt_gc_get_stats();
    assert_u64_eq(unreachable.tracked_object_count, 0, "unreachable cycle should be reclaimed");
}


static void test_global_root_registration_and_release(void) {
    rt_gc_register_global_root(&g_test_global_root);
    rt_gc_register_global_root(&g_test_global_root);

    NodeObj* root = alloc_node();
    root->next = alloc_node();
    g_test_global_root = root;

    rt_gc_collect(rt_thread_state());
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 2, "global root should keep object graph alive");

    g_test_global_root = NULL;
    rt_gc_unregister_global_root(&g_test_global_root);

    rt_gc_collect(rt_thread_state());
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "unregistered global root should allow reclamation");
}


static void test_nested_shadow_stack_frames(void) {
    void* outer_slots[1] = {NULL};
    void* inner_slots[1] = {NULL};
    RtRootFrame outer;
    RtRootFrame inner;

    rt_root_frame_init(&outer, outer_slots, 1);
    rt_root_frame_init(&inner, inner_slots, 1);

    rt_push_roots(rt_thread_state(), &outer);
    rt_root_slot_store(&outer, 0, alloc_node());

    rt_push_roots(rt_thread_state(), &inner);
    rt_root_slot_store(&inner, 0, alloc_node());

    rt_gc_collect(rt_thread_state());
    RtGcStats both_alive = rt_gc_get_stats();
    assert_u64_eq(both_alive.tracked_object_count, 2, "both root frames should keep their objects alive");

    rt_root_slot_store(&inner, 0, NULL);
    rt_pop_roots(rt_thread_state());

    rt_gc_collect(rt_thread_state());
    RtGcStats outer_only = rt_gc_get_stats();
    assert_u64_eq(outer_only.tracked_object_count, 1, "popped inner frame should release its object");

    rt_root_slot_store(&outer, 0, NULL);
    rt_pop_roots(rt_thread_state());

    rt_gc_collect(rt_thread_state());
    RtGcStats none_alive = rt_gc_get_stats();
    assert_u64_eq(none_alive.tracked_object_count, 0, "popped outer frame should release final object");
}


static void test_threshold_trigger_under_pressure(void) {
    for (uint64_t i = 0; i < 5000; i++) {
        alloc_leaf(i);
    }

    RtGcStats stats = rt_gc_get_stats();
    if (stats.tracked_object_count >= 5000) {
        fail("threshold-triggered GC should reclaim some objects during pressure allocation");
    }

    rt_gc_collect(rt_thread_state());
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "explicit collection should reclaim pressure allocations");
}


static void test_high_churn_stabilizes(void) {
    for (uint64_t round = 0; round < 50; round++) {
        for (uint64_t i = 0; i < 2000; i++) {
            alloc_leaf((round * 2000) + i);
        }
    }

    rt_gc_collect(rt_thread_state());
    RtGcStats stats = rt_gc_get_stats();
    assert_u64_eq(stats.tracked_object_count, 0, "churn test should end with zero live objects");
    if (stats.next_gc_threshold < (64u * 1024u)) {
        fail("threshold should never drop below minimum");
    }
}


int main(void) {
    rt_init();

    test_no_roots_reclaim();
    test_rooted_chain_survives_then_reclaims();
    test_cycle_reachable_then_unreachable();
    test_global_root_registration_and_release();
    test_nested_shadow_stack_frames();
    test_threshold_trigger_under_pressure();
    test_high_churn_stabilizes();

    rt_shutdown();
    puts("test_gc_stress: ok");
    return 0;
}
