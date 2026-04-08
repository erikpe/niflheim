#include "runtime.h"

#include <stdio.h>
#include <string.h>


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

static const void* HASH_ONLY_METHODS[1] = {
    (const void*)0x1111,
};

static const void* HASH_ONLY_INTERFACE_TABLES[2] = {
    HASH_ONLY_METHODS,
    NULL,
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
    .interface_tables = HASH_ONLY_INTERFACE_TABLES,
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


static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static const char* interface_name_or_unknown_for_test(const RtInterfaceType* interface_type) {
    if (interface_type == NULL || interface_type->debug_name == NULL) {
        return "<unknown>";
    }
    return interface_type->debug_name;
}

static const void* const* lookup_interface_table_for_test(
    const RtType* concrete_type,
    const RtInterfaceType* interface_type
) {
    if (interface_type == NULL) {
        rt_panic("lookup_interface_table_for_test called with NULL interface_type");
    }
    if (concrete_type == NULL || concrete_type->interface_tables == NULL) {
        return NULL;
    }
    if (interface_type->slot_index >= concrete_type->interface_slot_count) {
        return NULL;
    }

    const void* method_table = concrete_type->interface_tables[interface_type->slot_index];
    if (method_table == NULL) {
        return NULL;
    }

    return (const void* const*)method_table;
}

static void* checked_cast_interface_for_test(void* obj, const RtInterfaceType* expected_interface) {
    if (obj == NULL) {
        return NULL;
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    if (lookup_interface_table_for_test(header->type, expected_interface) != NULL) {
        return obj;
    }

    rt_panic_bad_cast(header->type->debug_name, interface_name_or_unknown_for_test(expected_interface));
}

static int run_case(const char* name) {
    if (strcmp(name, "non_implementing_object") == 0) {
        void* obj = alloc_leaf(&PLAIN_TYPE);
        (void)checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE);
        return 0;
    }

    if (strcmp(name, "interface_to_interface_failure") == 0) {
        void* obj = alloc_leaf(&HASH_ONLY_TYPE);
        void* hashable_value = checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE);
        (void)checked_cast_interface_for_test(hashable_value, &EQUALABLE_INTERFACE);
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