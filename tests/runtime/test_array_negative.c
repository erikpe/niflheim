#include "runtime.h"

#include <stdio.h>
#include <string.h>


static int run_case(const char* name) {
    if (strcmp(name, "get_negative") == 0) {
        void* arr = rt_array_new_u8(1u);
        (void)rt_array_get_u8(arr, -1);
        return 0;
    }

    if (strcmp(name, "slice_negative") == 0) {
        void* arr = rt_array_new_u8(1u);
        (void)rt_array_slice_u8(arr, -1, 0);
        return 0;
    }

    fprintf(stderr, "unknown case: %s\n", name);
    return 2;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: test_array_negative <case>\n");
        return 2;
    }

    rt_init();
    int rc = run_case(argv[1]);
    rt_shutdown();
    return rc;
}
