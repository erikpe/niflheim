#include "runtime.h"

#include <stdio.h>
#include <stdlib.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .slot_index = 0u,
    .method_count = 1u,
    .reserved0 = 0u,
};

static const RtInterfaceType EQUALABLE_INTERFACE = {
    .debug_name = "Equalable",
    .slot_index = 1u,
    .method_count = 1u,
    .reserved0 = 0u,
};

static const void* KEY_HASHABLE_METHODS[1] = {
    (const void*)0x1111,
};

static const void* KEY_EQUALABLE_METHODS[1] = {
    (const void*)0x2222,
};

static const RtInterfaceImpl KEY_INTERFACES[2] = {
    {
        .interface_type = &HASHABLE_INTERFACE,
        .method_table = KEY_HASHABLE_METHODS,
        .method_count = 1u,
        .reserved0 = 0u,
    },
    {
        .interface_type = &EQUALABLE_INTERFACE,
        .method_table = KEY_EQUALABLE_METHODS,
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
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
    .legacy_interfaces = KEY_INTERFACES,
    .legacy_interface_count = 2u,
    .reserved3 = 0u,
};

static const RtType DERIVED_KEY_TYPE = {
    .type_id = 0x44455256u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = 24u,
    .debug_name = "DerivedKey",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
    .super_type = &KEY_TYPE,
    .interface_tables = NULL,
    .interface_slot_count = 0u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
    .legacy_interfaces = KEY_INTERFACES,
    .legacy_interface_count = 2u,
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


static void fail(const char* message) {
    fprintf(stderr, "test_interface_metadata: %s\n", message);
    exit(1);
}


static void test_rt_type_exposes_slice1_slotted_interface_fields(void) {
    if (HASHABLE_INTERFACE.slot_index != 0u) {
        fail("Hashable should expose slot_index in interface descriptor");
    }
    if (EQUALABLE_INTERFACE.slot_index != 1u) {
        fail("Equalable should expose slot_index in interface descriptor");
    }
    if (KEY_TYPE.interface_tables != NULL) {
        fail("slice 1 should leave direct interface table storage unset");
    }
    if (KEY_TYPE.interface_slot_count != 0u) {
        fail("slice 1 should leave interface slot table count at zero before slot assignment");
    }
    if (KEY_TYPE.legacy_interfaces != KEY_INTERFACES) {
        fail("slice 1 should preserve legacy compact interface metadata");
    }
    if (KEY_TYPE.legacy_interface_count != 2u) {
        fail("slice 1 should preserve legacy interface metadata count");
    }
}


static void test_find_interface_impl_finds_matching_descriptor(void) {
    const RtInterfaceImpl* hashable = rt_find_interface_impl(&KEY_TYPE, &HASHABLE_INTERFACE);
    if (hashable == NULL) {
        fail("expected Hashable metadata record");
    }
    if (hashable->interface_type != &HASHABLE_INTERFACE) {
        fail("returned interface metadata should preserve descriptor pointer");
    }
    if (hashable->method_table != KEY_HASHABLE_METHODS) {
        fail("returned interface metadata should preserve method table pointer");
    }
    if (hashable->method_count != 1u) {
        fail("returned interface metadata should preserve method count");
    }

    const RtInterfaceImpl* inherited = rt_find_interface_impl(&DERIVED_KEY_TYPE, &HASHABLE_INTERFACE);
    if (inherited == NULL) {
        fail("derived type should expose inherited Hashable metadata record");
    }
    if (inherited->method_table != KEY_HASHABLE_METHODS) {
        fail("derived type should preserve inherited method table pointer");
    }
}


static void test_find_interface_impl_returns_null_for_missing_or_empty_metadata(void) {
    if (rt_find_interface_impl(&KEY_TYPE, NULL) != NULL) {
        fail("NULL interface descriptor should not match");
    }
    if (rt_find_interface_impl(NULL, &HASHABLE_INTERFACE) != NULL) {
        fail("NULL concrete type should not match");
    }
    if (rt_find_interface_impl(&PLAIN_TYPE, &HASHABLE_INTERFACE) != NULL) {
        fail("type without interface metadata should not match");
    }
    if (
        rt_find_interface_impl(
            &KEY_TYPE,
            &((RtInterfaceType){.debug_name = "Missing", .slot_index = 99u, .method_count = 1u, .reserved0 = 0u})
        )
        != NULL
    ) {
        fail("different interface descriptor pointer should not match");
    }
}


int main(void) {
    test_rt_type_exposes_slice1_slotted_interface_fields();
    test_find_interface_impl_finds_matching_descriptor();
    test_find_interface_impl_returns_null_for_missing_or_empty_metadata();

    puts("test_interface_metadata: ok");
    return 0;
}