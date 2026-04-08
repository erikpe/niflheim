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

static const void* KEY_INTERFACE_TABLES[1] = {
    HASHABLE_METHODS,
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
    .interface_slot_count = 1u,
    .reserved1 = 0u,
    .class_vtable = NULL,
    .class_vtable_count = 0u,
    .reserved2 = 0u,
    .legacy_interfaces = NULL,
    .legacy_interface_count = 0u,
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

static void* lookup_interface_method_for_test(void* obj, const RtInterfaceType* interface_type, uint32_t slot) {
    if (obj == NULL) {
        rt_panic_null_deref();
    }
    if (interface_type == NULL) {
        rt_panic("interface dispatch test helper called with NULL interface_type");
    }

    const RtObjHeader* header = (const RtObjHeader*)obj;
    if (header->type->interface_tables == NULL || interface_type->slot_index >= header->type->interface_slot_count) {
        rt_panic_bad_cast(header->type->debug_name, interface_type->debug_name);
    }

    const void* method_table = header->type->interface_tables[interface_type->slot_index];
    if (method_table == NULL) {
        rt_panic_bad_cast(header->type->debug_name, interface_type->debug_name);
    }
    if (slot >= interface_type->method_count) {
        rt_panic("interface dispatch: invalid interface method slot");
    }

    const void* method = ((const void* const*)method_table)[slot];
    if (method == NULL) {
        rt_panic("interface dispatch: null interface method entry");
    }
    return (void*)method;
}

static int run_case(const char* name) {
    if (strcmp(name, "null_receiver") == 0) {
        (void)lookup_interface_method_for_test(NULL, &HASHABLE_INTERFACE, 0u);
        return 0;
    }

    if (strcmp(name, "missing_interface") == 0) {
        void* obj = alloc_leaf(&PLAIN_TYPE);
        (void)lookup_interface_method_for_test(obj, &HASHABLE_INTERFACE, 0u);
        return 0;
    }

    if (strcmp(name, "slot_out_of_bounds") == 0) {
        void* obj = alloc_leaf(&KEY_TYPE);
        (void)lookup_interface_method_for_test(obj, &HASHABLE_INTERFACE, 2u);
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