#include "runtime.h"
#include "array.h"

#include <stddef.h>
#include <string.h>


typedef struct RtArrayObj {
    RtObjHeader header;
    uint64_t len;
    uint64_t element_kind;
    uint64_t element_size;
    uint8_t data[];
} RtArrayObj;


enum {
    RT_ARRAY_KIND_I64 = 1u,
    RT_ARRAY_KIND_U64 = 2u,
    RT_ARRAY_KIND_U8 = 3u,
    RT_ARRAY_KIND_BOOL = 4u,
    RT_ARRAY_KIND_DOUBLE = 5u,
    RT_ARRAY_KIND_REF = 6u,
};


static void rt_array_trace_ref(void* obj, void (*mark_ref)(void** slot));

RtType rt_type_array_primitive_desc = {
    .type_id = 0x41525031u,
    .flags = RT_TYPE_FLAG_LEAF | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtArrayObj),
    .debug_name = "ArrayPrimitive",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

RtType rt_type_array_reference_desc = {
    .type_id = 0x41525231u,
    .flags = RT_TYPE_FLAG_HAS_REFS | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtArrayObj),
    .debug_name = "ArrayReference",
    .trace_fn = rt_array_trace_ref,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};


static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static uint64_t rt_mul_u64_checked(uint64_t a, uint64_t b) {
    if (a != 0 && b > UINT64_MAX / a) {
        rt_panic_oom();
    }
    return a * b;
}

static uint64_t rt_add_u64_checked(uint64_t a, uint64_t b) {
    if (b > UINT64_MAX - a) {
        rt_panic_oom();
    }
    return a + b;
}

static uint64_t rt_array_payload_bytes(uint64_t len, uint64_t element_size) {
    uint64_t base = offsetof(RtArrayObj, data) - sizeof(RtObjHeader);
    uint64_t data_bytes = rt_mul_u64_checked(len, element_size);
    return rt_add_u64_checked(base, data_bytes);
}

static RtArrayObj* rt_require_array_obj(const void* array_obj, const char* api_name) {
    rt_require(array_obj != NULL, "Array API called with null object");

    RtArrayObj* array = (RtArrayObj*)array_obj;
    const RtType* type = array->header.type;
    if (type != &rt_type_array_primitive_desc && type != &rt_type_array_reference_desc) {
        rt_panic(api_name);
    }
    return array;
}

static RtArrayObj* rt_require_array_kind(const void* array_obj, uint64_t expected_kind, const char* api_name) {
    RtArrayObj* array = rt_require_array_obj(array_obj, api_name);
    if (array->element_kind != expected_kind) {
        rt_panic(api_name);
    }
    return array;
}

static void rt_require_index_in_bounds(const RtArrayObj* array, uint64_t index, const char* api_name) {
    if (index >= array->len) {
        rt_panic(api_name);
    }
}

static void rt_require_slice_range(const RtArrayObj* array, uint64_t start, uint64_t end, const char* api_name) {
    if (start > end || end > array->len) {
        rt_panic(api_name);
    }
}

static void rt_array_trace_ref(void* obj, void (*mark_ref)(void** slot)) {
    RtArrayObj* array = (RtArrayObj*)obj;
    if (array->element_kind != RT_ARRAY_KIND_REF) {
        rt_panic("rt_array_trace_ref: invalid element kind");
    }

    void** elements = (void**)(void*)array->data;
    for (uint64_t i = 0; i < array->len; i++) {
        mark_ref(&elements[i]);
    }
}

static void* rt_array_new(uint64_t len, uint64_t element_kind, uint64_t element_size, const RtType* type) {
    RtArrayObj* array = (RtArrayObj*)rt_alloc_obj(
        rt_thread_state(),
        type,
        rt_array_payload_bytes(len, element_size)
    );
    array->len = len;
    array->element_kind = element_kind;
    array->element_size = element_size;
    return (void*)array;
}

static void* rt_array_slice(const void* array_obj, uint64_t kind, uint64_t start, uint64_t end, const char* api_name) {
    const RtArrayObj* source = rt_require_array_kind(array_obj, kind, api_name);
    rt_require_slice_range(source, start, end, api_name);

    uint64_t slice_len = end - start;
    const RtType* type = source->header.type;
    RtArrayObj* slice = (RtArrayObj*)rt_array_new(slice_len, source->element_kind, source->element_size, type);

    uint64_t byte_offset = rt_mul_u64_checked(start, source->element_size);
    uint64_t copy_bytes = rt_mul_u64_checked(slice_len, source->element_size);
    if (copy_bytes > 0) {
        memcpy(slice->data, source->data + byte_offset, (size_t)copy_bytes);
    }

    return (void*)slice;
}

void* rt_array_new_i64(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_I64, sizeof(int64_t), &rt_type_array_primitive_desc);
}

void* rt_array_new_u64(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_U64, sizeof(uint64_t), &rt_type_array_primitive_desc);
}

void* rt_array_new_u8(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_U8, sizeof(uint8_t), &rt_type_array_primitive_desc);
}

void* rt_array_new_bool(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_BOOL, sizeof(int64_t), &rt_type_array_primitive_desc);
}

void* rt_array_new_double(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_DOUBLE, sizeof(double), &rt_type_array_primitive_desc);
}

void* rt_array_new_ref(uint64_t len) {
    return rt_array_new(len, RT_ARRAY_KIND_REF, sizeof(void*), &rt_type_array_reference_desc);
}

uint64_t rt_array_len(const void* array_obj) {
    return rt_require_array_obj(array_obj, "rt_array_len: object is not array")->len;
}

int64_t rt_array_get_i64(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_I64, "rt_array_get_i64: object is not i64[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_i64: index out of bounds");
    return ((int64_t*)(void*)array->data)[index];
}

uint64_t rt_array_get_u64(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_U64, "rt_array_get_u64: object is not u64[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_u64: index out of bounds");
    return ((uint64_t*)(void*)array->data)[index];
}

uint64_t rt_array_get_u8(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_U8, "rt_array_get_u8: object is not u8[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_u8: index out of bounds");
    return (uint64_t)((uint8_t*)(void*)array->data)[index];
}

int64_t rt_array_get_bool(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_BOOL, "rt_array_get_bool: object is not bool[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_bool: index out of bounds");
    return ((int64_t*)(void*)array->data)[index];
}

double rt_array_get_double(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_DOUBLE, "rt_array_get_double: object is not double[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_double: index out of bounds");
    return ((double*)(void*)array->data)[index];
}

void* rt_array_get_ref(const void* array_obj, uint64_t index) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_REF, "rt_array_get_ref: object is not ref[]");
    rt_require_index_in_bounds(array, index, "rt_array_get_ref: index out of bounds");
    return ((void**)(void*)array->data)[index];
}

void rt_array_set_i64(void* array_obj, uint64_t index, int64_t value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_I64, "rt_array_set_i64: object is not i64[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_i64: index out of bounds");
    ((int64_t*)(void*)array->data)[index] = value;
}

void rt_array_set_u64(void* array_obj, uint64_t index, uint64_t value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_U64, "rt_array_set_u64: object is not u64[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_u64: index out of bounds");
    ((uint64_t*)(void*)array->data)[index] = value;
}

void rt_array_set_u8(void* array_obj, uint64_t index, uint64_t value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_U8, "rt_array_set_u8: object is not u8[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_u8: index out of bounds");
    ((uint8_t*)(void*)array->data)[index] = (uint8_t)value;
}

void rt_array_set_bool(void* array_obj, uint64_t index, int64_t value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_BOOL, "rt_array_set_bool: object is not bool[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_bool: index out of bounds");
    ((int64_t*)(void*)array->data)[index] = value != 0 ? 1 : 0;
}

void rt_array_set_double(void* array_obj, uint64_t index, double value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_DOUBLE, "rt_array_set_double: object is not double[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_double: index out of bounds");
    ((double*)(void*)array->data)[index] = value;
}

void rt_array_set_ref(void* array_obj, uint64_t index, void* value) {
    RtArrayObj* array = rt_require_array_kind(array_obj, RT_ARRAY_KIND_REF, "rt_array_set_ref: object is not ref[]");
    rt_require_index_in_bounds(array, index, "rt_array_set_ref: index out of bounds");
    ((void**)(void*)array->data)[index] = value;
}

void* rt_array_slice_i64(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_I64, start, end, "rt_array_slice_i64: invalid slice range");
}

void* rt_array_slice_u64(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_U64, start, end, "rt_array_slice_u64: invalid slice range");
}

void* rt_array_slice_u8(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_U8, start, end, "rt_array_slice_u8: invalid slice range");
}

void* rt_array_slice_bool(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_BOOL, start, end, "rt_array_slice_bool: invalid slice range");
}

void* rt_array_slice_double(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_DOUBLE, start, end, "rt_array_slice_double: invalid slice range");
}

void* rt_array_slice_ref(const void* array_obj, uint64_t start, uint64_t end) {
    return rt_array_slice(array_obj, RT_ARRAY_KIND_REF, start, end, "rt_array_slice_ref: invalid slice range");
}
