#include "runtime.h"
#include "runtime_dbg.h"
#include "gc_tracked_set.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct PairObj {
    RtObjHeader header;
    void* left;
    void* right;
    uint64_t value;
} PairObj;


static const uint32_t PAIR_POINTER_OFFSETS[] = {
    (uint32_t)offsetof(PairObj, left),
    (uint32_t)offsetof(PairObj, right),
};


static const RtType PAIR_TYPE = {
    .type_id = 301,
    .flags = RT_TYPE_FLAG_HAS_REFS,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(PairObj),
    .debug_name = "TrackedSetPair",
    .trace_fn = NULL,
    .pointer_offsets = PAIR_POINTER_OFFSETS,
    .pointer_offsets_count = 2,
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
    fprintf(stderr, "test_tracked_set_gc_integration: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(
            stderr,
            "test_tracked_set_gc_integration: %s (actual=%llu expected=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)expected
        );
        exit(1);
    }
}


static void assert_u64_at_least(uint64_t actual, uint64_t minimum, const char* message) {
    if (actual < minimum) {
        fprintf(
            stderr,
            "test_tracked_set_gc_integration: %s (actual=%llu minimum=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)minimum
        );
        exit(1);
    }
}


static PairObj* alloc_pair(uint64_t value) {
    uint64_t payload = sizeof(PairObj) - sizeof(RtObjHeader);
    PairObj* obj = (PairObj*)rt_alloc_obj(rt_thread_state(), &PAIR_TYPE, payload);
    obj->value = value;
    return obj;
}


static PairObj* build_rooted_chain(
    RtRootFrame* frame,
    uint32_t root_slot_index,
    uint32_t temp_slot_index,
    uint64_t start_value,
    uint64_t length
) {
    if (length == 0u) {
        fail("rooted chain length must be non-zero");
    }

    PairObj* head = alloc_pair(start_value);
    rt_dbg_root_slot_store(frame, root_slot_index, head);

    PairObj* current = head;
    for (uint64_t step = 1u; step < length; step++) {
        PairObj* next = alloc_pair(start_value + step);
        rt_dbg_root_slot_store(frame, temp_slot_index, next);
        current->left = next;
        next->right = current;
        current = next;
    }

    rt_dbg_root_slot_store(frame, temp_slot_index, NULL);
    return head;
}


static void build_unrooted_chain(uint64_t start_value, uint64_t length) {
    if (length == 0u) {
        fail("unrooted chain length must be non-zero");
    }

    PairObj* head = alloc_pair(start_value);
    PairObj* current = head;
    for (uint64_t step = 1u; step < length; step++) {
        PairObj* next = alloc_pair(start_value + step);
        current->left = next;
        next->right = current;
        current = next;
    }
}


static void assert_chain_live(PairObj* head, uint64_t start_value, uint64_t length) {
    PairObj* current = head;
    PairObj* previous = NULL;

    for (uint64_t step = 0u; step < length; step++) {
        if (current == NULL) {
            fail("rooted chain ended early after GC churn");
        }
        if (!rt_gc_tracked_set_contains(&current->header)) {
            fail("live rooted object should remain present in the tracked set");
        }
        assert_u64_eq(current->value, start_value + step, "rooted chain value should survive GC churn");
        if (current->right != previous) {
            fail("rooted chain back-link should survive GC churn");
        }

        previous = current;
        current = (PairObj*)current->left;
    }

    if (current != NULL) {
        fail("rooted chain should have the expected length after GC churn");
    }
}


static void test_rooted_graph_survives_churn_and_unrooted_graphs_are_reclaimed(void) {
    enum {
        ROOTED_CHAIN_LENGTH = 96,
        GARBAGE_CHAIN_COUNT = 64,
        GARBAGE_CHAIN_LENGTH = 5,
        ROUNDS = 4,
    };

    const uint64_t garbage_objects_per_round = GARBAGE_CHAIN_COUNT * GARBAGE_CHAIN_LENGTH;
    const uint64_t rooted_base_value = 1000u;

    rt_gc_reset_state();
    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();

    void* slots[2] = {NULL, NULL};
    RtRootFrame frame;
    rt_dbg_root_frame_init(&frame, slots, 2u);
    rt_dbg_push_roots(rt_thread_state(), &frame);

    PairObj* rooted_head = build_rooted_chain(&frame, 0u, 1u, rooted_base_value, ROOTED_CHAIN_LENGTH);

    rt_gc_collect();
    assert_u64_eq(
        rt_gc_get_stats().tracked_object_count,
        ROOTED_CHAIN_LENGTH,
        "initial rooted graph should survive collection"
    );
    assert_chain_live(rooted_head, rooted_base_value, ROOTED_CHAIN_LENGTH);

    rt_gc_tracked_set_enable_probe_stats(1);
    rt_gc_tracked_set_reset_probe_stats();

    uint64_t next_value = 100000u;
    for (uint64_t round = 0u; round < ROUNDS; round++) {
        for (uint64_t chain = 0u; chain < GARBAGE_CHAIN_COUNT; chain++) {
            build_unrooted_chain(next_value, GARBAGE_CHAIN_LENGTH);
            next_value += GARBAGE_CHAIN_LENGTH;
        }

        rt_gc_collect();
        assert_u64_eq(
            rt_gc_get_stats().tracked_object_count,
            ROOTED_CHAIN_LENGTH,
            "collection should reclaim unrooted graphs while keeping the rooted graph alive"
        );
        assert_chain_live(rooted_head, rooted_base_value, ROOTED_CHAIN_LENGTH);
    }

    RtGcTrackedSetProbeStats probe_stats = rt_gc_tracked_set_get_probe_stats();
    assert_u64_eq(
        probe_stats.insert_calls,
        ROUNDS * garbage_objects_per_round,
        "real-object churn should count tracked-set inserts through rt_gc_track_allocation"
    );
    assert_u64_eq(
        probe_stats.remove_calls,
        ROUNDS * garbage_objects_per_round,
        "sweeping unrooted graphs should remove every dead object from the tracked set"
    );
    assert_u64_eq(
        probe_stats.tombstone_compactions,
        ROUNDS - 1u,
        "subsequent churn rounds should trigger tombstone compaction before reinsertion"
    );
    assert_u64_eq(
        probe_stats.maintenance_calls,
        ROUNDS - 1u,
        "real-object churn should only use tombstone compaction maintenance in this setup"
    );
    assert_u64_at_least(
        probe_stats.contains_calls,
        (ROUNDS * ROOTED_CHAIN_LENGTH) + 1u,
        "GC mark should route real pointer-offset traversal through tracked-set contains"
    );

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();

    rt_dbg_root_slot_store(&frame, 0u, NULL);
    rt_dbg_root_slot_store(&frame, 1u, NULL);
    rt_dbg_pop_roots(rt_thread_state());

    rt_gc_collect();
    assert_u64_eq(
        rt_gc_get_stats().tracked_object_count,
        0u,
        "clearing the final root should allow the rooted graph to be reclaimed"
    );

    rt_gc_reset_state();
}


int main(void) {
    rt_init();

    test_rooted_graph_survives_churn_and_unrooted_graphs_are_reclaimed();

    rt_shutdown();
    puts("test_tracked_set_gc_integration: ok");
    return 0;
}