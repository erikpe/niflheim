#include "runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct LeafObj {
    RtObjHeader header;
    uint64_t value;
} LeafObj;


static const RtType LEAF_TYPE = {
    .type_id = 101,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(LeafObj),
    .debug_name = "PoolLeaf",
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
    fprintf(stderr, "test_gc_tracking_pool: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(
            stderr,
            "test_gc_tracking_pool: %s (actual=%llu expected=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)expected
        );
        exit(1);
    }
}


static void assert_u64_nonzero(uint64_t actual, const char* message) {
    if (actual == 0) {
        fprintf(stderr, "test_gc_tracking_pool: %s\n", message);
        exit(1);
    }
}


static void assert_tracking_pool_accounting(RtGcTrackingPoolStats stats, const char* context) {
    if (stats.allocation_requests != stats.pool_hits + stats.pool_misses) {
        fprintf(
            stderr,
            "test_gc_tracking_pool: %s (requests=%llu hits=%llu misses=%llu)\n",
            context,
            (unsigned long long)stats.allocation_requests,
            (unsigned long long)stats.pool_hits,
            (unsigned long long)stats.pool_misses
        );
        exit(1);
    }
}


static LeafObj* alloc_leaf(uint64_t value) {
    uint64_t payload = sizeof(LeafObj) - sizeof(RtObjHeader);
    LeafObj* leaf = (LeafObj*)rt_alloc_obj(rt_thread_state(), &LEAF_TYPE, payload);
    leaf->value = value;
    return leaf;
}


static void test_tracking_pool_stats_surface_reports_chunked_allocations(void) {
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    for (uint64_t i = 0; i < 8; i++) {
        alloc_leaf(i);
    }

    RtGcTrackingPoolStats stats = rt_gc_get_tracking_pool_stats();
    assert_tracking_pool_accounting(stats, "tracking-pool stats should balance requests against hits and misses");
    assert_u64_eq(stats.allocation_requests, 8, "tracking-pool stats should count allocation requests");
    assert_u64_nonzero(stats.pool_misses, "tracked-node pool should report at least one pool miss");
    assert_u64_nonzero(stats.pool_hits, "tracked-node pool should report pool hits after the first chunk allocation");
    assert_u64_eq(stats.chunk_allocations, stats.pool_misses, "each pool miss should correspond to one chunk allocation");
    assert_u64_eq(stats.nodes_returned, 0, "tracked nodes are not returned to the pool until patch 3");

    rt_gc_collect();
    rt_gc_reset_state();
}


static void test_tracking_pool_stats_reports_chunk_refill_when_free_list_exhausts(void) {
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    alloc_leaf(1);
    RtGcTrackingPoolStats first_stats = rt_gc_get_tracking_pool_stats();
    assert_u64_eq(first_stats.chunk_allocations, 1, "first tracked allocation should allocate exactly one chunk");
    assert_u64_eq(first_stats.pool_misses, 1, "first tracked allocation should miss the pool once");

    uint64_t inferred_chunk_capacity = first_stats.available_nodes + 1;
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    for (uint64_t i = 0; i < inferred_chunk_capacity + 1; i++) {
        alloc_leaf(i);
    }

    RtGcTrackingPoolStats refill_stats = rt_gc_get_tracking_pool_stats();
    assert_tracking_pool_accounting(refill_stats, "chunk refill stats should balance requests against hits and misses");
    assert_u64_eq(
        refill_stats.allocation_requests,
        inferred_chunk_capacity + 1,
        "chunk refill test should issue the expected number of allocation requests"
    );
    assert_u64_eq(refill_stats.chunk_allocations, 2, "exhausting the first chunk should allocate a second chunk");
    assert_u64_eq(refill_stats.pool_misses, 2, "exhausting the first chunk should cause a second pool miss");

    rt_gc_collect();
    rt_gc_reset_state();
}


static void test_tracking_pool_stats_can_observe_reuse_when_pooling_exists(void) {
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    alloc_leaf(1);
    RtGcTrackingPoolStats first_stats = rt_gc_get_tracking_pool_stats();
    uint64_t inferred_chunk_capacity = first_stats.available_nodes + 1;

    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    uint64_t allocation_count = inferred_chunk_capacity + 8;
    for (uint64_t i = 0; i < allocation_count; i++) {
        alloc_leaf(i);
    }
    rt_gc_collect();
    RtGcTrackingPoolStats after_first_collect = rt_gc_get_tracking_pool_stats();
    assert_tracking_pool_accounting(
        after_first_collect,
        "tracking-pool stats should remain balanced after collection"
    );
    assert_u64_eq(
        after_first_collect.nodes_returned,
        allocation_count,
        "collection should return all dead tracked nodes to the pool"
    );
    uint64_t chunk_allocations_before_reuse = after_first_collect.chunk_allocations;

    for (uint64_t i = 0; i < allocation_count; i++) {
        alloc_leaf(100 + i);
    }
    RtGcTrackingPoolStats after_second_round = rt_gc_get_tracking_pool_stats();
    assert_tracking_pool_accounting(
        after_second_round,
        "tracking-pool stats should remain balanced after another allocation round"
    );
    assert_u64_eq(
        after_second_round.chunk_allocations,
        chunk_allocations_before_reuse,
        "reallocating after collection should reuse returned tracked nodes without allocating new chunks"
    );
    if (after_second_round.pool_hits <= after_first_collect.pool_hits) {
        fail("reallocating after collection should consume returned tracked nodes as pool hits");
    }

    rt_gc_collect();
    rt_gc_reset_state();
}


static void test_tracking_pool_stats_reset_clears_counters(void) {
    rt_gc_reset_state();
    rt_gc_reset_tracking_pool_stats();

    alloc_leaf(1);
    RtGcTrackingPoolStats before_reset = rt_gc_get_tracking_pool_stats();
    if (before_reset.allocation_requests == 0) {
        fail("tracking-pool stats should observe at least one allocation request before reset");
    }

    rt_gc_reset_tracking_pool_stats();
    RtGcTrackingPoolStats after_reset = rt_gc_get_tracking_pool_stats();
    assert_u64_eq(after_reset.allocation_requests, 0, "tracking-pool stats reset should clear allocation requests");
    assert_u64_eq(after_reset.pool_hits, 0, "tracking-pool stats reset should clear pool hits");
    assert_u64_eq(after_reset.pool_misses, 0, "tracking-pool stats reset should clear pool misses");
    assert_u64_eq(after_reset.chunk_allocations, 0, "tracking-pool stats reset should clear chunk allocations");
    assert_u64_eq(after_reset.nodes_returned, 0, "tracking-pool stats reset should clear returned-node counts");
    assert_u64_eq(after_reset.available_nodes, 0, "tracking-pool stats reset should clear available-node counts");

    rt_gc_collect();
    rt_gc_reset_state();
}


int main(void) {
    rt_init();

    test_tracking_pool_stats_surface_reports_chunked_allocations();
    test_tracking_pool_stats_reports_chunk_refill_when_free_list_exhausts();
    test_tracking_pool_stats_can_observe_reuse_when_pooling_exists();
    test_tracking_pool_stats_reset_clears_counters();

    rt_shutdown();
    puts("test_gc_tracking_pool: ok");
    return 0;
}