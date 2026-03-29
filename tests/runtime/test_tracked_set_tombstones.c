#include "runtime.h"
#include "gc_tracked_set.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static void fail(const char* message) {
    fprintf(stderr, "test_tracked_set_tombstones: %s\n", message);
    exit(1);
}


int main(void) {
    rt_gc_tracked_set_reset();

    enum {
        OBJ_COUNT = 1024,
    };

    RtObjHeader* objs = (RtObjHeader*)calloc(OBJ_COUNT, sizeof(RtObjHeader));
    if (objs == NULL) {
        fail("allocation failed");
    }

    for (uint64_t i = 0; i < OBJ_COUNT; i++) {
        rt_gc_tracked_set_insert(&objs[i]);
    }
    for (uint64_t i = 0; i < OBJ_COUNT; i++) {
        rt_gc_tracked_set_remove(&objs[i]);
    }

    RtObjHeader missing = {0};
    if (rt_gc_tracked_set_contains(&missing)) {
        fail("missing object should not be reported as present");
    }

    rt_gc_tracked_set_insert(&missing);
    if (!rt_gc_tracked_set_contains(&missing)) {
        fail("reinserted object should be found");
    }

    rt_gc_tracked_set_remove(&missing);
    if (rt_gc_tracked_set_contains(&missing)) {
        fail("removed object should not remain present");
    }

    free(objs);
    rt_gc_tracked_set_reset();
    puts("test_tracked_set_tombstones: ok");
    return 0;
}