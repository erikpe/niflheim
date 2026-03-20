#include "runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .method_count = 2u,
    .reserved0 = 0u,
};

static const RtInterfaceType COMPARABLE_INTERFACE = {
    .debug_name = "Comparable",
    .method_count = 1u,
    .reserved0 = 0u,
};

static const void* KEY_HASHABLE_METHODS[2] = {
    (const void*)0x1111,
    (const void*)0x2222,
};

static const void* KEY_COMPARABLE_METHODS[1] = {
    (const void*)0x3333,
};

static const RtInterfaceImpl KEY_INTERFACES[2] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = KEY_HASHABLE_METHODS,
        .method_count = 2u,
        .reserved0 = 0u,
    },
    {
        .interface_type = &COMPARABLE_INTERFACE,
        .method_table = KEY_COMPARABLE_METHODS,
        .method_count = 1u,
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
    .interfaces = KEY_INTERFACES,
    .interface_count = 2u,
    .reserved1 = 0u,
};


static void fail(const char* message) {
    fprintf(stderr, "test_interface_dispatch: %s\n", message);
    exit(1);
}

static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static void test_lookup_interface_method_returns_slot_ordered_entries(void) {
    void* obj = alloc_leaf(&KEY_TYPE);

    if (rt_lookup_interface_method(obj, &HASHABLE_INTERFACE, 0u) != (void*)0x1111) {
        fail("expected Hashable slot 0 method pointer");
    }
    if (rt_lookup_interface_method(obj, &HASHABLE_INTERFACE, 1u) != (void*)0x2222) {
        fail("expected Hashable slot 1 method pointer");
    }
    if (rt_lookup_interface_method(obj, &COMPARABLE_INTERFACE, 0u) != (void*)0x3333) {
        fail("expected Comparable slot 0 method pointer");
    }
}


int main(void) {
    rt_init();
    test_lookup_interface_method_returns_slot_ordered_entries();
    rt_shutdown();
    puts("test_interface_dispatch: ok");
    return 0;
}