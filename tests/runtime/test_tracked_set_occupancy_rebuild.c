#include "runtime.h"
#include "gc_tracked_set.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static void fail(const char* message) {
    fprintf(stderr, "test_tracked_set_occupancy_rebuild: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(
            stderr,
            "test_tracked_set_occupancy_rebuild: %s (actual=%llu expected=%llu)\n",
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
            "test_tracked_set_occupancy_rebuild: %s (actual=%llu minimum=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)minimum
        );
        exit(1);
    }
}


static void test_occupancy_triggered_same_capacity_rebuild_preserves_membership(void) {
    enum {
        INITIAL_INSERTS = 1024,
        REMOVED_COUNT = 128,
        TOTAL_OBJECTS = INITIAL_INSERTS + 1,
    };

    RtObjHeader* objs = (RtObjHeader*)calloc(TOTAL_OBJECTS, sizeof(RtObjHeader));
    if (objs == NULL) {
        fail("allocation failed");
    }

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);

    for (uint64_t index = 0; index < INITIAL_INSERTS; index++) {
        rt_gc_tracked_set_insert(&objs[index]);
    }
    for (uint64_t index = 0; index < REMOVED_COUNT; index++) {
        rt_gc_tracked_set_remove(&objs[index]);
    }

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_insert(&objs[INITIAL_INSERTS]);

    RtGcTrackedSetProbeStats stats = rt_gc_tracked_set_get_probe_stats();
    assert_u64_eq(
        stats.insert_calls,
        1u,
        "occupancy-path regression should isolate the triggering insert"
    );
    assert_u64_eq(
        stats.maintenance_calls,
        1u,
        "inserting with occupied slots at threshold should trigger exactly one maintenance pass"
    );
    assert_u64_eq(
        stats.tombstone_compactions,
        0u,
        "occupancy-driven maintenance should not be reported as a tombstone compaction"
    );
    assert_u64_at_least(
        stats.insert_probes,
        1u,
        "occupancy-path regression should still record the triggering insert probe"
    );

    for (uint64_t index = REMOVED_COUNT; index < INITIAL_INSERTS; index++) {
        if (!rt_gc_tracked_set_contains(&objs[index])) {
            fail("live members should remain reachable after same-capacity occupancy rebuild");
        }
    }
    for (uint64_t index = 0; index < REMOVED_COUNT; index++) {
        if (rt_gc_tracked_set_contains(&objs[index])) {
            fail("removed members should stay absent after same-capacity occupancy rebuild");
        }
    }
    if (!rt_gc_tracked_set_contains(&objs[INITIAL_INSERTS])) {
        fail("new member should be present after same-capacity occupancy rebuild");
    }

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
    free(objs);
}


int main(void) {
    test_occupancy_triggered_same_capacity_rebuild_preserves_membership();
    puts("test_tracked_set_occupancy_rebuild: ok");
    return 0;
}