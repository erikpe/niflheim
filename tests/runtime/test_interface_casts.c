#include "runtime.h"

#include <stdio.h>
#include <stdlib.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .method_count = 1u,
    .reserved0 = 0u,
};

static const RtInterfaceType COMPARABLE_INTERFACE = {
    .debug_name = "Comparable",
    .method_count = 1u,
    .reserved0 = 0u,
};

static const void* HASH_ONLY_METHODS[1] = {
    (const void*)0x1111,
};

static const void* KEY_HASHABLE_METHODS[1] = {
    (const void*)0x2222,
};

static const void* KEY_COMPARABLE_METHODS[1] = {
    (const void*)0x3333,
};

static const RtInterfaceImpl HASH_ONLY_INTERFACES[1] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = HASH_ONLY_METHODS,
        .method_count = 1u,
        .reserved0 = 0u,
    },
};

static const RtInterfaceImpl KEY_INTERFACES[2] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = KEY_HASHABLE_METHODS,
        .method_count = 1u,
        .reserved0 = 0u,
    },
    {
        .interface_type = &COMPARABLE_INTERFACE,
        .method_table = KEY_COMPARABLE_METHODS,
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
    .interfaces = HASH_ONLY_INTERFACES,
    .interface_count = 1u,
    .reserved1 = 0u,
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
    fprintf(stderr, "test_interface_casts: %s\n", message);
    exit(1);
}

static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static void test_checked_cast_interface_accepts_null(void) {
    if (rt_checked_cast_interface(NULL, &HASHABLE_INTERFACE) != NULL) {
        fail("null interface cast should return null");
    }
}

static void test_checked_cast_interface_accepts_implementing_object(void) {
    void* obj = alloc_leaf(&KEY_TYPE);
    if (rt_checked_cast_interface(obj, &HASHABLE_INTERFACE) != obj) {
        fail("implementing object should cast to supported interface");
    }
}

static void test_checked_cast_interface_checks_interface_value_at_runtime(void) {
    void* obj = alloc_leaf(&KEY_TYPE);
    void* hashable_value = rt_checked_cast_interface(obj, &HASHABLE_INTERFACE);
    if (rt_checked_cast_interface(hashable_value, &COMPARABLE_INTERFACE) != obj) {
        fail("interface-to-interface cast should preserve the original object pointer");
    }
}

static void test_checked_cast_interface_accepts_single_interface_impl(void) {
    void* obj = alloc_leaf(&HASH_ONLY_TYPE);
    if (rt_checked_cast_interface(obj, &HASHABLE_INTERFACE) != obj) {
        fail("single-interface implementation should cast successfully");
    }
}

int main(void) {
    rt_init();

    test_checked_cast_interface_accepts_null();
    test_checked_cast_interface_accepts_implementing_object();
    test_checked_cast_interface_checks_interface_value_at_runtime();
    test_checked_cast_interface_accepts_single_interface_impl();

    rt_shutdown();
    puts("test_interface_casts: ok");
    return 0;
}