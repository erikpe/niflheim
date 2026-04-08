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

static const void* HASH_ONLY_METHODS[1] = {
    (const void*)0x1111,
};

static const void* KEY_HASHABLE_METHODS[1] = {
    (const void*)0x2222,
};

static const void* KEY_EQUALABLE_METHODS[1] = {
    (const void*)0x3333,
};

static const void* HASH_ONLY_INTERFACE_TABLES[2] = {
    HASH_ONLY_METHODS,
    NULL,
};

static const void* KEY_INTERFACE_TABLES[2] = {
    KEY_HASHABLE_METHODS,
    KEY_EQUALABLE_METHODS,
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


static void fail(const char* message) {
    fprintf(stderr, "test_interface_casts: %s\n", message);
    exit(1);
}

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

static uint64_t is_instance_of_interface_for_test(void* obj, const RtInterfaceType* expected_interface) {
    if (obj == NULL) {
        return 0u;
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    return lookup_interface_table_for_test(header->type, expected_interface) != NULL ? 1u : 0u;
}

static void* checked_cast_interface_for_test(void* obj, const RtInterfaceType* expected_interface) {
    if (obj == NULL) {
        return NULL;
    }
    if (is_instance_of_interface_for_test(obj, expected_interface) != 0u) {
        return obj;
    }

    RtObjHeader* header = (RtObjHeader*)obj;
    rt_panic_bad_cast(header->type->debug_name, interface_name_or_unknown_for_test(expected_interface));
}

static void test_checked_cast_interface_accepts_null(void) {
    if (checked_cast_interface_for_test(NULL, &HASHABLE_INTERFACE) != NULL) {
        fail("null interface cast should return null");
    }
}

static void test_checked_cast_interface_accepts_implementing_object(void) {
    void* obj = alloc_leaf(&KEY_TYPE);
    if (checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE) != obj) {
        fail("implementing object should cast to supported interface");
    }
}

static void test_checked_cast_interface_checks_interface_value_at_runtime(void) {
    void* obj = alloc_leaf(&KEY_TYPE);
    void* hashable_value = checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE);
    if (checked_cast_interface_for_test(hashable_value, &EQUALABLE_INTERFACE) != obj) {
        fail("interface-to-interface cast should preserve the original object pointer");
    }
}

static void test_checked_cast_interface_accepts_single_interface_impl(void) {
    void* obj = alloc_leaf(&HASH_ONLY_TYPE);
    if (checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE) != obj) {
        fail("single-interface implementation should cast successfully");
    }
}

static void test_checked_cast_accepts_derived_instance_for_base_type(void) {
    void* obj = alloc_leaf(&DERIVED_KEY_TYPE);
    if (rt_checked_cast(obj, &KEY_TYPE) != obj) {
        fail("derived object should cast to its base runtime type");
    }
    if (checked_cast_interface_for_test(obj, &HASHABLE_INTERFACE) != obj) {
        fail("derived object should cast to inherited interface metadata");
    }
}

static void test_is_instance_of_interface_uses_slot_tables(void) {
    void* hash_only = alloc_leaf(&HASH_ONLY_TYPE);
    void* key = alloc_leaf(&KEY_TYPE);
    void* derived = alloc_leaf(&DERIVED_KEY_TYPE);

    if (is_instance_of_interface_for_test(NULL, &HASHABLE_INTERFACE) != 0u) {
        fail("null should not be an instance of any interface");
    }
    if (is_instance_of_interface_for_test(hash_only, &HASHABLE_INTERFACE) != 1u) {
        fail("HashOnly should report its implemented interface via slot tables");
    }
    if (is_instance_of_interface_for_test(hash_only, &EQUALABLE_INTERFACE) != 0u) {
        fail("HashOnly should not report an unimplemented interface");
    }
    if (is_instance_of_interface_for_test(key, &EQUALABLE_INTERFACE) != 1u) {
        fail("Key should report Equalable via slot tables");
    }
    if (is_instance_of_interface_for_test(derived, &HASHABLE_INTERFACE) != 1u) {
        fail("DerivedKey should report inherited interfaces via populated slot tables");
    }
}

static void test_is_instance_of_type_walks_superclass_chain(void) {
    void* derived = alloc_leaf(&DERIVED_KEY_TYPE);
    void* base = alloc_leaf(&KEY_TYPE);

    if (rt_is_instance_of_type(derived, &KEY_TYPE) != 1u) {
        fail("derived object should be an instance of its base type");
    }
    if (rt_is_instance_of_type(derived, &DERIVED_KEY_TYPE) != 1u) {
        fail("derived object should be an instance of its own type");
    }
    if (rt_is_instance_of_type(base, &DERIVED_KEY_TYPE) != 0u) {
        fail("base object should not be an instance of derived type");
    }
}

int main(void) {
    rt_init();

    test_checked_cast_interface_accepts_null();
    test_checked_cast_interface_accepts_implementing_object();
    test_checked_cast_interface_checks_interface_value_at_runtime();
    test_checked_cast_interface_accepts_single_interface_impl();
    test_checked_cast_accepts_derived_instance_for_base_type();
    test_is_instance_of_interface_uses_slot_tables();
    test_is_instance_of_type_walks_superclass_chain();

    rt_shutdown();
    puts("test_interface_casts: ok");
    return 0;
}