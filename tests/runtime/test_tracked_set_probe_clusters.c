#include "runtime.h"
#include "gc_tracked_set.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


enum {
    TEST_TRACKED_SET_INITIAL_CAPACITY = 1024u,
    TEST_WRAP_BUCKET = TEST_TRACKED_SET_INITIAL_CAPACITY - 2u,
    TEST_CLUSTER_KEY_COUNT = 5u,
};


static void fail(const char* message) {
    fprintf(stderr, "test_tracked_set_probe_clusters: %s\n", message);
    exit(1);
}


static uint64_t test_hash_ptr_uint64(uintptr_t value) {
    uint64_t x = (uint64_t)value;
    x ^= x >> 33;
    x *= 0xff51afd7ed558ccdu;
    x ^= x >> 33;
    x *= 0xc4ceb9fe1a85ec53u;
    x ^= x >> 33;
    return x;
}


static void collect_cluster_keys(RtObjHeader** keys, uint64_t key_count) {
    uint64_t found = 0u;
    uint64_t mask = TEST_TRACKED_SET_INITIAL_CAPACITY - 1u;

    for (uintptr_t candidate = 0x1000u; found < key_count; candidate += 8u) {
        if ((test_hash_ptr_uint64(candidate) & mask) != TEST_WRAP_BUCKET) {
            continue;
        }
        keys[found] = (RtObjHeader*)candidate;
        found++;
        if (candidate > UINTPTR_MAX - 8u && found < key_count) {
            break;
        }
    }

    if (found != key_count) {
        fail("failed to synthesize enough keys for the target probe cluster");
    }
}


static void assert_probe_totals(
    RtGcTrackedSetProbeStats stats,
    uint64_t insert_calls,
    uint64_t contains_calls,
    uint64_t remove_calls,
    uint64_t insert_probes,
    uint64_t contains_probes,
    uint64_t remove_probes,
    const char* message
) {
    if (
        stats.insert_calls != insert_calls ||
        stats.contains_calls != contains_calls ||
        stats.remove_calls != remove_calls ||
        stats.insert_probes != insert_probes ||
        stats.contains_probes != contains_probes ||
        stats.remove_probes != remove_probes
    ) {
        fprintf(
            stderr,
            "test_tracked_set_probe_clusters: %s (insert_calls=%llu contains_calls=%llu remove_calls=%llu insert_probes=%llu contains_probes=%llu remove_probes=%llu)\n",
            message,
            (unsigned long long)stats.insert_calls,
            (unsigned long long)stats.contains_calls,
            (unsigned long long)stats.remove_calls,
            (unsigned long long)stats.insert_probes,
            (unsigned long long)stats.contains_probes,
            (unsigned long long)stats.remove_probes
        );
        exit(1);
    }
}


static void test_probe_cluster_wraparound_and_tombstone_reuse(void) {
    RtObjHeader* keys[TEST_CLUSTER_KEY_COUNT] = {NULL};
    collect_cluster_keys(keys, TEST_CLUSTER_KEY_COUNT);

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);

    rt_gc_tracked_set_insert(keys[0]);
    rt_gc_tracked_set_insert(keys[1]);
    rt_gc_tracked_set_insert(keys[2]);

    rt_gc_tracked_set_reset_probe_stats();
    if (!rt_gc_tracked_set_contains(keys[2])) {
        fail("lookup should find the key that wrapped from the end of the table to slot zero");
    }
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        1u,
        0u,
        0u,
        3u,
        0u,
        "wrap-around lookup should probe across the end of the table into slot zero"
    );

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_remove(keys[1]);
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        0u,
        1u,
        0u,
        0u,
        2u,
        "removing the middle cluster member should stop on the expected wrapped slot"
    );

    rt_gc_tracked_set_reset_probe_stats();
    if (!rt_gc_tracked_set_contains(keys[2])) {
        fail("lookup after tombstone creation should still reach later keys in the wrapped cluster");
    }
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        1u,
        0u,
        0u,
        3u,
        0u,
        "tombstones should not break later lookups in the same wrapped probe cluster"
    );

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_insert(keys[3]);
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        1u,
        0u,
        0u,
        4u,
        0u,
        0u,
        "reinsertion after a tombstone should scan to the later NULL while remembering the first tombstone"
    );

    rt_gc_tracked_set_reset_probe_stats();
    if (!rt_gc_tracked_set_contains(keys[3])) {
        fail("reinserted key should be reachable from the first tombstone slot in the cluster");
    }
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        1u,
        0u,
        0u,
        2u,
        0u,
        "tombstone reuse should place the new key in the first tombstone rather than a later NULL slot"
    );

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_insert(keys[4]);
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        1u,
        0u,
        0u,
        4u,
        0u,
        0u,
        "a later colliding insert should stop at the first NULL after the wrapped live cluster"
    );

    rt_gc_tracked_set_reset_probe_stats();
    if (rt_gc_tracked_set_contains(keys[1])) {
        fail("removed key should stay absent after tombstone reuse and later wrapped inserts");
    }
    assert_probe_totals(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        1u,
        0u,
        0u,
        5u,
        0u,
        "missing-key lookup should walk the full wrapped cluster until the first NULL"
    );

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
}


int main(void) {
    test_probe_cluster_wraparound_and_tombstone_reuse();
    puts("test_tracked_set_probe_clusters: ok");
    return 0;
}