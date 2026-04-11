#include "runtime.h"
#include "gc_tracked_set.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static void fail(const char* message) {
    fprintf(stderr, "test_tracked_set_probe_behavior: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(
            stderr,
            "test_tracked_set_probe_behavior: %s (actual=%llu expected=%llu)\n",
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
            "test_tracked_set_probe_behavior: %s (actual=%llu minimum=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)minimum
        );
        exit(1);
    }
}


static void assert_stats_zero(RtGcTrackedSetProbeStats stats, const char* context) {
    if (
        stats.insert_calls != 0u ||
        stats.contains_calls != 0u ||
        stats.remove_calls != 0u ||
        stats.insert_probes != 0u ||
        stats.contains_probes != 0u ||
        stats.remove_probes != 0u ||
        stats.max_probe_depth != 0u ||
        stats.maintenance_calls != 0u ||
        stats.tombstone_compactions != 0u
    ) {
        fprintf(stderr, "test_tracked_set_probe_behavior: %s\n", context);
        exit(1);
    }
}


static void assert_operation_counts(
    RtGcTrackedSetProbeStats stats,
    uint64_t insert_calls,
    uint64_t contains_calls,
    uint64_t remove_calls,
    const char* context
) {
    if (
        stats.insert_calls != insert_calls ||
        stats.contains_calls != contains_calls ||
        stats.remove_calls != remove_calls
    ) {
        fprintf(
            stderr,
            "test_tracked_set_probe_behavior: %s (insert=%llu contains=%llu remove=%llu)\n",
            context,
            (unsigned long long)stats.insert_calls,
            (unsigned long long)stats.contains_calls,
            (unsigned long long)stats.remove_calls
        );
        exit(1);
    }
}


static void test_probe_stats_are_opt_in(void) {
    RtObjHeader objs[4] = {0};

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();

    rt_gc_tracked_set_insert(&objs[0]);
    (void)rt_gc_tracked_set_contains(&objs[0]);
    rt_gc_tracked_set_remove(&objs[0]);

    assert_stats_zero(
        rt_gc_tracked_set_get_probe_stats(),
        "probe stats should stay zero while observability is disabled"
    );

    rt_gc_tracked_set_reset();
}


static void test_probe_stats_keep_operation_paths_separate(void) {
    RtObjHeader obj = {0};

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_insert(&obj);
    assert_operation_counts(
        rt_gc_tracked_set_get_probe_stats(),
        1u,
        0u,
        0u,
        "insert should record only insert-call counters"
    );

    rt_gc_tracked_set_reset_probe_stats();
    (void)rt_gc_tracked_set_contains(&obj);
    assert_operation_counts(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        1u,
        0u,
        "contains should record only contains-call counters"
    );

    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_remove(&obj);
    assert_operation_counts(
        rt_gc_tracked_set_get_probe_stats(),
        0u,
        0u,
        1u,
        "remove should record only remove-call counters"
    );

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
}


static void test_duplicate_insert_keeps_single_membership(void) {
    RtObjHeader obj = {0};

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);

    rt_gc_tracked_set_insert(&obj);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_insert(&obj);

    RtGcTrackedSetProbeStats stats = rt_gc_tracked_set_get_probe_stats();
    assert_operation_counts(
        stats,
        1u,
        0u,
        0u,
        "duplicate insert should still use only the insert operation path"
    );
    assert_u64_at_least(
        stats.insert_probes,
        1u,
        "duplicate insert should still probe for an existing entry"
    );

    rt_gc_tracked_set_remove(&obj);
    if (rt_gc_tracked_set_contains(&obj)) {
        fail("duplicate insert should not leave multiple memberships behind after one remove");
    }

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
}


static void test_probe_stats_report_churn_heavy_workload(void) {
    enum {
        INITIAL_ACTIVE = 384,
        CHURN_STEP = 288,
        ROUNDS = 4,
        TOTAL_OBJECTS = INITIAL_ACTIVE + (ROUNDS * CHURN_STEP),
    };

    RtObjHeader* objs = (RtObjHeader*)calloc(TOTAL_OBJECTS, sizeof(RtObjHeader));
    if (objs == NULL) {
        fail("allocation failed");
    }

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);
    rt_gc_tracked_set_reset_probe_stats();

    for (uint64_t index = 0; index < INITIAL_ACTIVE; index++) {
        rt_gc_tracked_set_insert(&objs[index]);
    }
    rt_gc_tracked_set_reset_probe_stats();

    uint64_t active_start = 0u;
    uint64_t next_insert = INITIAL_ACTIVE;
    for (uint64_t round = 0; round < ROUNDS; round++) {
        for (uint64_t index = active_start; index < active_start + INITIAL_ACTIVE; index++) {
            if (!rt_gc_tracked_set_contains(&objs[index])) {
                fail("active object should be found during churn workload");
            }
        }

        for (uint64_t index = active_start; index < active_start + CHURN_STEP; index++) {
            rt_gc_tracked_set_remove(&objs[index]);
            if (rt_gc_tracked_set_contains(&objs[index])) {
                fail("removed object should not remain present during churn workload");
            }
        }

        for (uint64_t step = 0; step < CHURN_STEP; step++) {
            uint64_t index = next_insert + step;
            rt_gc_tracked_set_insert(&objs[index]);
            if (!rt_gc_tracked_set_contains(&objs[index])) {
                fail("newly inserted object should be found during churn workload");
            }
        }

        active_start += CHURN_STEP;
        next_insert += CHURN_STEP;
    }

    RtGcTrackedSetProbeStats stats = rt_gc_tracked_set_get_probe_stats();
    assert_u64_eq(
        stats.insert_calls,
        ROUNDS * CHURN_STEP,
        "probe stats should count tracked-set insert operations"
    );
    assert_u64_eq(
        stats.contains_calls,
        ROUNDS * (INITIAL_ACTIVE + CHURN_STEP + CHURN_STEP),
        "probe stats should count tracked-set contains operations"
    );
    assert_u64_eq(
        stats.remove_calls,
        ROUNDS * CHURN_STEP,
        "probe stats should count tracked-set remove operations"
    );
    assert_u64_at_least(
        stats.insert_probes,
        stats.insert_calls,
        "tracked-set insert probe totals should be at least the number of insert calls"
    );
    assert_u64_at_least(
        stats.contains_probes,
        stats.contains_calls,
        "tracked-set contains probe totals should be at least the number of contains calls"
    );
    assert_u64_at_least(
        stats.remove_probes,
        stats.remove_calls,
        "tracked-set remove probe totals should be at least the number of remove calls"
    );
    assert_u64_at_least(
        stats.max_probe_depth,
        1u,
        "tracked-set churn workload should record a non-zero max probe depth"
    );
    assert_u64_eq(
        stats.tombstone_compactions,
        ROUNDS,
        "churn-heavy workload should trigger one tombstone compaction per remove-and-reinsert round"
    );
    assert_u64_eq(
        stats.maintenance_calls,
        ROUNDS,
        "churn-heavy workload should enter the maintenance path only through tombstone compaction after setup"
    );

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
    free(objs);
}


static void test_tombstone_compaction_preserves_live_members(void) {
    enum {
        INITIAL_ACTIVE = 384,
        REMOVED_COUNT = 288,
        TOTAL_OBJECTS = INITIAL_ACTIVE + 1,
    };

    RtObjHeader* objs = (RtObjHeader*)calloc(TOTAL_OBJECTS, sizeof(RtObjHeader));
    if (objs == NULL) {
        fail("allocation failed");
    }

    rt_gc_tracked_set_reset();
    rt_gc_tracked_set_enable_probe_stats(1);
    for (uint64_t index = 0; index < INITIAL_ACTIVE; index++) {
        rt_gc_tracked_set_insert(&objs[index]);
    }
    rt_gc_tracked_set_reset_probe_stats();

    for (uint64_t index = 0; index < REMOVED_COUNT; index++) {
        rt_gc_tracked_set_remove(&objs[index]);
    }

    rt_gc_tracked_set_insert(&objs[INITIAL_ACTIVE]);

    RtGcTrackedSetProbeStats stats = rt_gc_tracked_set_get_probe_stats();
    assert_u64_eq(
        stats.tombstone_compactions,
        1u,
        "inserting into a tombstone-dominated table below the normal occupancy threshold should compact once"
    );
    assert_u64_eq(
        stats.maintenance_calls,
        1u,
        "tombstone-dominated reinsertion should use exactly one maintenance pass"
    );

    for (uint64_t index = REMOVED_COUNT; index < INITIAL_ACTIVE; index++) {
        if (!rt_gc_tracked_set_contains(&objs[index])) {
            fail("live members should remain present after tombstone compaction");
        }
    }
    for (uint64_t index = 0; index < REMOVED_COUNT; index++) {
        if (rt_gc_tracked_set_contains(&objs[index])) {
            fail("removed members should stay absent after tombstone compaction");
        }
    }
    if (!rt_gc_tracked_set_contains(&objs[INITIAL_ACTIVE])) {
        fail("new member should be present after tombstone compaction");
    }

    rt_gc_tracked_set_enable_probe_stats(0);
    rt_gc_tracked_set_reset_probe_stats();
    rt_gc_tracked_set_reset();
    free(objs);
}


int main(void) {
    test_probe_stats_are_opt_in();
    test_probe_stats_keep_operation_paths_separate();
    test_duplicate_insert_keeps_single_membership();
    test_probe_stats_report_churn_heavy_workload();
    test_tombstone_compaction_preserves_live_members();
    puts("test_tracked_set_probe_behavior: ok");
    return 0;
}