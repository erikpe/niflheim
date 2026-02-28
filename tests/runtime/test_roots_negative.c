#include "runtime.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>


static int run_case(const char* name) {
    if (strcmp(name, "pop_underflow") == 0) {
        rt_pop_roots(rt_thread_state());
        return 0;
    }

    if (strcmp(name, "slot_store_oob") == 0) {
        void* slots[1] = {NULL};
        RtRootFrame frame;
        rt_root_frame_init(&frame, slots, 1);
        rt_push_roots(rt_thread_state(), &frame);
        rt_root_slot_store(&frame, 1, NULL);
        return 0;
    }

    if (strcmp(name, "slot_load_oob") == 0) {
        void* slots[1] = {NULL};
        RtRootFrame frame;
        rt_root_frame_init(&frame, slots, 1);
        rt_push_roots(rt_thread_state(), &frame);
        (void)rt_root_slot_load(&frame, 1);
        return 0;
    }

    if (strcmp(name, "register_global_null") == 0) {
        rt_gc_register_global_root(NULL);
        return 0;
    }

    if (strcmp(name, "unregister_global_null") == 0) {
        rt_gc_unregister_global_root(NULL);
        return 0;
    }

    fprintf(stderr, "unknown case: %s\n", name);
    return 2;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: test_roots_negative <case>\n");
        return 2;
    }

    rt_init();
    int rc = run_case(argv[1]);
    rt_shutdown();
    return rc;
}
