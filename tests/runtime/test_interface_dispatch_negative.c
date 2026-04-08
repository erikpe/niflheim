#include "runtime.h"

#include <stdio.h>
#include <string.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .slot_index = 0u,
    .method_count = 2u,
    .reserved0 = 0u,
};

static const void* HASHABLE_METHODS[2] = {
    (const void*)0x1111,
    (const void*)0x2222,
};

static const RtInterfaceImpl KEY_INTERFACES[1] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = HASHABLE_METHODS,
        .method_count = 2u,
        .reserved0 = 0u,
    },
};

static const RtType KEY_TYPE = {
    .type_id = 0x4B455931u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = 24u,
    .debug_name = "Key",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
    .legacy_interfaces = KEY_INTERFACES,
    .legacy_interface_count = 1u,
    .reserved3 = 0u,
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
    .interface_tables = NULL,
    .interface_slot_count = 0u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
    .legacy_interfaces = NULL,
    .legacy_interface_count = 0u,
    .reserved3 = 0u,
};


static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static int run_case(const char* name) {
    if (strcmp(name, "null_receiver") == 0) {
        (void)rt_lookup_interface_method(NULL, &HASHABLE_INTERFACE, 0u);
        return 0;
    }

    if (strcmp(name, "missing_interface") == 0) {
        void* obj = alloc_leaf(&PLAIN_TYPE);
        (void)rt_lookup_interface_method(obj, &HASHABLE_INTERFACE, 0u);
        return 0;
    }

    if (strcmp(name, "slot_out_of_bounds") == 0) {
        void* obj = alloc_leaf(&KEY_TYPE);
        (void)rt_lookup_interface_method(obj, &HASHABLE_INTERFACE, 2u);
        return 0;
    }

    fprintf(stderr, "unknown case: %s\n", name);
    return 2;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: test_interface_dispatch_negative <case>\n");
        return 2;
    }

    rt_init();
    int rc = run_case(argv[1]);
    rt_shutdown();
    return rc;
}