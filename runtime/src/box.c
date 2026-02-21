#include "runtime.h"
#include "box.h"

#include <stddef.h>

typedef struct RtBoxI64Obj {
    RtObjHeader header;
    int64_t value;
} RtBoxI64Obj;

typedef struct RtBoxU64Obj {
    RtObjHeader header;
    uint64_t value;
} RtBoxU64Obj;

typedef struct RtBoxU8Obj {
    RtObjHeader header;
    uint64_t value;
} RtBoxU8Obj;

typedef struct RtBoxBoolObj {
    RtObjHeader header;
    int64_t value;
} RtBoxBoolObj;

typedef struct RtBoxDoubleObj {
    RtObjHeader header;
    double value;
} RtBoxDoubleObj;

static RtType g_rt_type_box_i64 = {
    .type_id = 0x42495831u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(int64_t),
    .debug_name = "BoxI64",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_box_u64 = {
    .type_id = 0x42555831u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t),
    .debug_name = "BoxU64",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_box_u8 = {
    .type_id = 0x42553831u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t),
    .debug_name = "BoxU8",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_box_bool = {
    .type_id = 0x42424F31u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(int64_t),
    .debug_name = "BoxBool",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_box_double = {
    .type_id = 0x42445831u,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(double),
    .debug_name = "BoxDouble",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static RtBoxI64Obj* rt_require_box_i64_obj(const void* box_obj, const char* api_name) {
    rt_require(box_obj != NULL, "BoxI64 API called with null object");
    RtBoxI64Obj* box = (RtBoxI64Obj*)box_obj;
    if (box->header.type != &g_rt_type_box_i64) {
        rt_panic(api_name);
    }
    return box;
}

static RtBoxU64Obj* rt_require_box_u64_obj(const void* box_obj, const char* api_name) {
    rt_require(box_obj != NULL, "BoxU64 API called with null object");
    RtBoxU64Obj* box = (RtBoxU64Obj*)box_obj;
    if (box->header.type != &g_rt_type_box_u64) {
        rt_panic(api_name);
    }
    return box;
}

static RtBoxU8Obj* rt_require_box_u8_obj(const void* box_obj, const char* api_name) {
    rt_require(box_obj != NULL, "BoxU8 API called with null object");
    RtBoxU8Obj* box = (RtBoxU8Obj*)box_obj;
    if (box->header.type != &g_rt_type_box_u8) {
        rt_panic(api_name);
    }
    return box;
}

static RtBoxBoolObj* rt_require_box_bool_obj(const void* box_obj, const char* api_name) {
    rt_require(box_obj != NULL, "BoxBool API called with null object");
    RtBoxBoolObj* box = (RtBoxBoolObj*)box_obj;
    if (box->header.type != &g_rt_type_box_bool) {
        rt_panic(api_name);
    }
    return box;
}

static RtBoxDoubleObj* rt_require_box_double_obj(const void* box_obj, const char* api_name) {
    rt_require(box_obj != NULL, "BoxDouble API called with null object");
    RtBoxDoubleObj* box = (RtBoxDoubleObj*)box_obj;
    if (box->header.type != &g_rt_type_box_double) {
        rt_panic(api_name);
    }
    return box;
}

void* rt_box_i64_new(int64_t value) {
    RtBoxI64Obj* box = (RtBoxI64Obj*)rt_alloc_obj(rt_thread_state(), &g_rt_type_box_i64, sizeof(int64_t));
    box->value = value;
    return (void*)box;
}

void* rt_box_u64_new(uint64_t value) {
    RtBoxU64Obj* box = (RtBoxU64Obj*)rt_alloc_obj(rt_thread_state(), &g_rt_type_box_u64, sizeof(uint64_t));
    box->value = value;
    return (void*)box;
}

void* rt_box_u8_new(uint64_t value) {
    RtBoxU8Obj* box = (RtBoxU8Obj*)rt_alloc_obj(rt_thread_state(), &g_rt_type_box_u8, sizeof(uint64_t));
    box->value = (uint64_t)((uint8_t)value);
    return (void*)box;
}

void* rt_box_bool_new(int64_t value) {
    RtBoxBoolObj* box = (RtBoxBoolObj*)rt_alloc_obj(rt_thread_state(), &g_rt_type_box_bool, sizeof(int64_t));
    box->value = value != 0 ? 1 : 0;
    return (void*)box;
}

void* rt_box_double_new(double value) {
    RtBoxDoubleObj* box = (RtBoxDoubleObj*)rt_alloc_obj(rt_thread_state(), &g_rt_type_box_double, sizeof(double));
    box->value = value;
    return (void*)box;
}

int64_t rt_box_i64_get(const void* box_obj) {
    return rt_require_box_i64_obj(box_obj, "rt_box_i64_get: object is not BoxI64")->value;
}

uint64_t rt_box_u64_get(const void* box_obj) {
    return rt_require_box_u64_obj(box_obj, "rt_box_u64_get: object is not BoxU64")->value;
}

uint64_t rt_box_u8_get(const void* box_obj) {
    return rt_require_box_u8_obj(box_obj, "rt_box_u8_get: object is not BoxU8")->value;
}

int64_t rt_box_bool_get(const void* box_obj) {
    return rt_require_box_bool_obj(box_obj, "rt_box_bool_get: object is not BoxBool")->value;
}

double rt_box_double_get(const void* box_obj) {
    return rt_require_box_double_obj(box_obj, "rt_box_double_get: object is not BoxDouble")->value;
}
