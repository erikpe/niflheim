#include "runtime_dbg.h"

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
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
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
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
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

    rt_gc_collect();
    RtGcStats stats = rt_gc_get_stats();
    assert_u64_eq(stats.tracked_object_count, 0, "no roots should reclaim all objects");
    assert_u64_eq(stats.live_bytes, 0, "no roots should leave zero live bytes");
}


static void test_rooted_chain_survives_then_reclaims(void) {
    void* slots[1] = {NULL};
    RtRootFrame frame;
    rt_dbg_root_frame_init(&frame, slots, 1);
    rt_dbg_push_roots(rt_thread_state(), &frame);

    NodeObj* a = alloc_node();
    NodeObj* b = alloc_node();
    NodeObj* c = alloc_node();
    a->next = b;
    b->next = c;
    c->next = NULL;

    rt_dbg_root_slot_store(&frame, 0, a);

    rt_gc_collect();
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 3, "rooted chain should survive collection");

    rt_dbg_root_slot_store(&frame, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "cleared root should allow chain reclamation");
}


static void test_cycle_reachable_then_unreachable(void) {
    void* slots[1] = {NULL};
    RtRootFrame frame;
    rt_dbg_root_frame_init(&frame, slots, 1);
    rt_dbg_push_roots(rt_thread_state(), &frame);

    NodeObj* n1 = alloc_node();
    NodeObj* n2 = alloc_node();
    n1->next = n2;
    n2->next = n1;

    rt_dbg_root_slot_store(&frame, 0, n1);
    rt_gc_collect();
    RtGcStats reachable = rt_gc_get_stats();
    assert_u64_eq(reachable.tracked_object_count, 2, "reachable cycle should survive");

    rt_dbg_root_slot_store(&frame, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats unreachable = rt_gc_get_stats();
    assert_u64_eq(unreachable.tracked_object_count, 0, "unreachable cycle should be reclaimed");
}


static void test_global_root_registration_and_release(void) {
    rt_gc_register_global_root(&g_test_global_root);
    rt_gc_register_global_root(&g_test_global_root);

    NodeObj* root = alloc_node();
    root->next = alloc_node();
    g_test_global_root = root;

    rt_gc_collect();
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 2, "global root should keep object graph alive");

    g_test_global_root = NULL;
    rt_gc_unregister_global_root(&g_test_global_root);

    rt_gc_collect();
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "unregistered global root should allow reclamation");
}


static void test_nested_shadow_stack_frames(void) {
    void* outer_slots[1] = {NULL};
    void* inner_slots[1] = {NULL};
    RtRootFrame outer;
    RtRootFrame inner;

    rt_dbg_root_frame_init(&outer, outer_slots, 1);
    rt_dbg_root_frame_init(&inner, inner_slots, 1);

    rt_dbg_push_roots(rt_thread_state(), &outer);
    rt_dbg_root_slot_store(&outer, 0, alloc_node());

    rt_dbg_push_roots(rt_thread_state(), &inner);
    rt_dbg_root_slot_store(&inner, 0, alloc_node());

    rt_gc_collect();
    RtGcStats both_alive = rt_gc_get_stats();
    assert_u64_eq(both_alive.tracked_object_count, 2, "both root frames should keep their objects alive");

    rt_dbg_root_slot_store(&inner, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats outer_only = rt_gc_get_stats();
    assert_u64_eq(outer_only.tracked_object_count, 1, "popped inner frame should release its object");

    rt_dbg_root_slot_store(&outer, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats none_alive = rt_gc_get_stats();
    assert_u64_eq(none_alive.tracked_object_count, 0, "popped outer frame should release final object");
}


static void test_collect_without_explicit_argument(void) {
    void* slots[1] = {NULL};
    RtRootFrame frame;
    rt_dbg_root_frame_init(&frame, slots, 1);
    rt_dbg_push_roots(rt_thread_state(), &frame);

    NodeObj* root = alloc_node();
    root->next = alloc_node();
    rt_dbg_root_slot_store(&frame, 0, root);

    rt_gc_collect();
    RtGcStats alive = rt_gc_get_stats();
    assert_u64_eq(alive.tracked_object_count, 2, "collect should use the current thread state implicitly");

    rt_dbg_root_slot_store(&frame, 0, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "zero-arg collect should reclaim cleared roots");
}


static void test_threshold_trigger_under_pressure(void) {
    for (uint64_t i = 0; i < 5000; i++) {
        alloc_leaf(i);
    }

    RtGcStats stats = rt_gc_get_stats();
    if (stats.tracked_object_count >= 5000) {
        fail("threshold-triggered GC should reclaim some objects during pressure allocation");
    }

    rt_gc_collect();
    RtGcStats cleared = rt_gc_get_stats();
    assert_u64_eq(cleared.tracked_object_count, 0, "explicit collection should reclaim pressure allocations");
}


static void test_high_churn_stabilizes(void) {
    for (uint64_t round = 0; round < 50; round++) {
        for (uint64_t i = 0; i < 2000; i++) {
            alloc_leaf((round * 2000) + i);
        }
    }

    rt_gc_collect();
    RtGcStats stats = rt_gc_get_stats();
    assert_u64_eq(stats.tracked_object_count, 0, "churn test should end with zero live objects");
    if (stats.next_gc_threshold < (64u * 1024u)) {
        fail("threshold should never drop below minimum");
    }
}


static void test_repeated_collect_reuses_tracking_nodes(void) {
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    alloc_leaf(1);
    RtGcTrackingPoolStats first_stats = rt_gc_get_tracking_pool_stats();
    uint64_t inferred_chunk_capacity = first_stats.available_nodes + 1;

    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    uint64_t round_allocation_count = inferred_chunk_capacity + 8;
    uint64_t expected_chunk_allocations = 0;
    for (uint64_t round = 0; round < 4; round++) {
        for (uint64_t index = 0; index < round_allocation_count; index++) {
            alloc_leaf((round * round_allocation_count) + index);
        }
        rt_gc_collect();

        RtGcTrackingPoolStats stats = rt_gc_get_tracking_pool_stats();
        if (round == 0) {
            expected_chunk_allocations = stats.chunk_allocations;
            if (expected_chunk_allocations == 0) {
                fail("first churn round should allocate at least one tracked-object chunk");
            }
        } else if (stats.chunk_allocations != expected_chunk_allocations) {
            fail("repeated allocate/collect cycles should reuse tracked nodes without allocating more chunks");
        }
    }

    RtGcStats final_stats = rt_gc_get_stats();
    assert_u64_eq(final_stats.tracked_object_count, 0, "repeated tracking-node reuse test should end with zero live objects");
    rt_gc_reset_state();
}


int main(void) {
    rt_init();

    test_no_roots_reclaim();
    test_rooted_chain_survives_then_reclaims();
    test_cycle_reachable_then_unreachable();
    test_global_root_registration_and_release();
    test_nested_shadow_stack_frames();
    test_collect_without_explicit_argument();
    test_threshold_trigger_under_pressure();
    test_high_churn_stabilizes();
    test_repeated_collect_reuses_tracking_nodes();

    rt_shutdown();
    puts("test_gc_stress: ok");
    return 0;
}
