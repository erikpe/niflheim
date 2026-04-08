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

static const void* KEY_INTERFACE_TABLES[2] = {
    KEY_HASHABLE_METHODS,
    KEY_EQUALABLE_METHODS,
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
    .interface_tables = KEY_INTERFACE_TABLES,
    .interface_slot_count = 2u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
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
    .interface_tables = KEY_INTERFACE_TABLES,
    .interface_slot_count = 2u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
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
};


static void fail(const char* message) {
    fprintf(stderr, "test_interface_metadata: %s\n", message);
    exit(1);
}


static const void* const* lookup_interface_table(const RtType* concrete_type, const RtInterfaceType* interface_type) {
    if (concrete_type == NULL || interface_type == NULL) {
        return NULL;
    }
    if (concrete_type->interface_tables == NULL) {
        return NULL;
    }
    if (interface_type->slot_index >= concrete_type->interface_slot_count) {
        return NULL;
    }

    const void* method_table = concrete_type->interface_tables[interface_type->slot_index];
    return (const void* const*)method_table;
}


static void test_rt_type_exposes_slotted_interface_tables(void) {
    if (HASHABLE_INTERFACE.slot_index != 0u) {
        fail("Hashable should expose slot_index in interface descriptor");
    }
    if (EQUALABLE_INTERFACE.slot_index != 1u) {
        fail("Equalable should expose slot_index in interface descriptor");
    }
    if (KEY_TYPE.interface_tables != KEY_INTERFACE_TABLES) {
        fail("Key should expose direct interface table storage");
    }
    if (KEY_TYPE.interface_slot_count != 2u) {
        fail("Key should expose the full interface slot count");
    }
}


static void test_lookup_interface_table_returns_slot_ordered_tables(void) {
    const void* const* hashable = lookup_interface_table(&KEY_TYPE, &HASHABLE_INTERFACE);
    if (hashable == NULL) {
        fail("expected Hashable slot table");
    }
    if (hashable[0] != (const void*)0x1111) {
        fail("Hashable slot 0 should preserve the emitted method entry");
    }
    if (hashable[1] != (const void*)0x2222) {
        fail("Hashable slot 1 should preserve the emitted method entry");
    }

    const void* const* equalable = lookup_interface_table(&KEY_TYPE, &EQUALABLE_INTERFACE);
    if (equalable == NULL) {
        fail("expected Equalable slot table");
    }
    if (equalable[0] != (const void*)0x2222) {
        fail("Equalable slot 0 should preserve the emitted method entry");
    }

    const void* const* inherited = lookup_interface_table(&DERIVED_KEY_TYPE, &HASHABLE_INTERFACE);
    if (inherited == NULL) {
        fail("derived type should expose inherited Hashable slot table");
    }
    if (inherited != hashable) {
        fail("derived type should preserve inherited method table pointer");
    }
}

static void test_lookup_interface_table_returns_null_for_missing_or_empty_slots(void) {
    if (lookup_interface_table(&KEY_TYPE, NULL) != NULL) {
        fail("NULL interface descriptor should not match a slot table");
    }
    if (lookup_interface_table(NULL, &HASHABLE_INTERFACE) != NULL) {
        fail("NULL concrete type should not match a slot table");
    }
    if (lookup_interface_table(&PLAIN_TYPE, &HASHABLE_INTERFACE) != NULL) {
        fail("types without interface tables should return null");
    }
    if (lookup_interface_table(&KEY_TYPE, &((RtInterfaceType){.debug_name = "Missing", .slot_index = 99u, .method_count = 1u, .reserved0 = 0u})) != NULL) {
        fail("missing interface slots should return null");
    }
}


int main(void) {
    test_rt_type_exposes_slotted_interface_tables();
    test_lookup_interface_table_returns_slot_ordered_tables();
    test_lookup_interface_table_returns_null_for_missing_or_empty_slots();

    puts("test_interface_metadata: ok");
    return 0;
}