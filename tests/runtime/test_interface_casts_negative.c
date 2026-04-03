#include "runtime.h"

#include <stdio.h>
#include <string.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .method_count = 1u,
    .reserved0 = 0u,
};

static const RtInterfaceType EQUALABLE_INTERFACE = {
    .debug_name = "Equalable",
    .method_count = 1u,
    .reserved0 = 0u,
};

static const void* HASH_ONLY_METHODS[1] = {
    (const void*)0x1111,
};

static const RtInterfaceImpl HASH_ONLY_INTERFACES[1] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = HASH_ONLY_METHODS,
        .method_count = 1u,
        .reserved0 = 0u,
    },
};

static const RtType HASH_ONLY_TYPE = {
    .type_id = 0x48415348u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = 24u,
    .debug_name = "HashOnly",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
    .super_type = NULL,
    .interfaces = HASH_ONLY_INTERFACES,
    .interface_count = 1u,
    .reserved1 = 0u,
};

static const RtType PLAIN_TYPE = {
    .type_id = 0x504C4149u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = 24u,
    .debug_name = "Plain",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
    .super_type = NULL,
    .interfaces = NULL,
    .interface_count = 0u,
    .reserved1 = 0u,
};


static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static int run_case(const char* name) {
    if (strcmp(name, "non_implementing_object") == 0) {
        void* obj = alloc_leaf(&PLAIN_TYPE);
        (void)rt_checked_cast_interface(obj, &HASHABLE_INTERFACE);
        return 0;
    }

    if (strcmp(name, "interface_to_interface_failure") == 0) {
        void* obj = alloc_leaf(&HASH_ONLY_TYPE);
        void* hashable_value = rt_checked_cast_interface(obj, &HASHABLE_INTERFACE);
        (void)rt_checked_cast_interface(hashable_value, &EQUALABLE_INTERFACE);
        return 0;
    }

    fprintf(stderr, "unknown case: %s\n", name);
    return 2;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: test_interface_casts_negative <case>\n");
        return 2;
    }

    rt_init();
    int rc = run_case(argv[1]);
    rt_shutdown();
    return rc;
}