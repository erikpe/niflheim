#include "runtime.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


static const RtInterfaceType HASHABLE_INTERFACE = {
    .debug_name = "Hashable",
    .slot_index = 0u,
    .method_count = 2u,
    .reserved0 = 0u,
};

static const RtInterfaceType EQUALABLE_INTERFACE = {
    .debug_name = "Equalable",
    .slot_index = 1u,
    .method_count = 1u,
    .reserved0 = 0u,
};

static const void* KEY_HASHABLE_METHODS[2] = {
    (const void*)0x1111,
    (const void*)0x2222,
};

static const void* KEY_EQUALABLE_METHODS[1] = {
    (const void*)0x3333,
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


static void fail(const char* message) {
    fprintf(stderr, "test_interface_dispatch: %s\n", message);
    exit(1);
}

static void* alloc_leaf(const RtType* type) {
    return rt_alloc_obj(rt_thread_state(), type, 0u);
}

static void* load_interface_method_from_slot_table_for_test(void* obj, const RtInterfaceType* interface_type, uint32_t slot) {
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

static void test_slot_table_dispatch_returns_slot_ordered_entries(void) {
    void* obj = alloc_leaf(&KEY_TYPE);

    if (load_interface_method_from_slot_table_for_test(obj, &HASHABLE_INTERFACE, 0u) != (void*)0x1111) {
        fail("expected Hashable slot 0 method pointer");
    }
    if (load_interface_method_from_slot_table_for_test(obj, &HASHABLE_INTERFACE, 1u) != (void*)0x2222) {
        fail("expected Hashable slot 1 method pointer");
    }
    if (load_interface_method_from_slot_table_for_test(obj, &EQUALABLE_INTERFACE, 0u) != (void*)0x3333) {
        fail("expected Equalable slot 0 method pointer");
    }
}


int main(void) {
    rt_init();
    test_slot_table_dispatch_returns_slot_ordered_entries();
    rt_shutdown();
    puts("test_interface_dispatch: ok");
    return 0;
}