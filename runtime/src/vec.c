#include "runtime.h"
#include "vec.h"

#include <stddef.h>

typedef struct RtVecStorageObj {
    RtObjHeader header;
    uint64_t capacity;
    void* elements[];
} RtVecStorageObj;

typedef struct RtVecObj {
    RtObjHeader header;
    uint64_t len;
    RtVecStorageObj* storage;
} RtVecObj;

static void rt_vec_trace(void* obj, void (*mark_ref)(void** slot));
static void rt_vec_storage_trace(void* obj, void (*mark_ref)(void** slot));

RtType rt_type_vec_desc = {
    .type_id = 0x56454331u,
    .flags = RT_TYPE_FLAG_HAS_REFS,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t) + sizeof(void*),
    .debug_name = "Vec",
    .trace_fn = rt_vec_trace,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static RtType g_rt_type_vec_storage = {
    .type_id = 0x56455331u,
    .flags = RT_TYPE_FLAG_HAS_REFS | RT_TYPE_FLAG_VARIABLE_SIZE,
    .abi_version = 1u,
    .align_bytes = 8u,
    .fixed_size_bytes = sizeof(RtObjHeader) + sizeof(uint64_t),
    .debug_name = "VecStorage",
    .trace_fn = rt_vec_storage_trace,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0u,
    .reserved0 = 0u,
};

static void rt_require(int condition, const char* message) {
    if (!condition) {
        rt_panic(message);
    }
}

static RtVecObj* rt_require_vec_obj(const void* vec_obj, const char* api_name) {
    rt_require(vec_obj != NULL, "Vec API called with null object");
    RtVecObj* vec = (RtVecObj*)vec_obj;
    if (vec->header.type != &rt_type_vec_desc) {
        rt_panic(api_name);
    }
    return vec;
}

static RtVecStorageObj* rt_vec_storage_new(uint64_t capacity) {
    RtVecStorageObj* storage = (RtVecStorageObj*)rt_alloc_obj(
        rt_thread_state(),
        &g_rt_type_vec_storage,
        sizeof(uint64_t) + (capacity * sizeof(void*))
    );
    storage->capacity = capacity;
    return storage;
}

static void rt_vec_grow_if_needed(RtVecObj* vec) {
    RtVecStorageObj* storage = vec->storage;
    rt_require(storage != NULL, "rt_vec_push: internal storage is null");

    if (vec->len < storage->capacity) {
        return;
    }

    uint64_t next_capacity = storage->capacity == 0 ? 4 : storage->capacity * 2;
    RtVecStorageObj* grown = rt_vec_storage_new(next_capacity);
    for (uint64_t index = 0; index < vec->len; index++) {
        grown->elements[index] = storage->elements[index];
    }
    vec->storage = grown;
}

static void rt_vec_trace(void* obj, void (*mark_ref)(void** slot)) {
    RtVecObj* vec = (RtVecObj*)obj;
    mark_ref((void**)&vec->storage);
}

static void rt_vec_storage_trace(void* obj, void (*mark_ref)(void** slot)) {
    RtVecStorageObj* storage = (RtVecStorageObj*)obj;
    for (uint64_t index = 0; index < storage->capacity; index++) {
        mark_ref(&storage->elements[index]);
    }
}

void* rt_vec_new(void) {
    RtThreadState* ts = rt_thread_state();
    RtRootFrame frame;
    void* slots[1] = {NULL};
    rt_root_frame_init(&frame, slots, 1);
    rt_push_roots(ts, &frame);

    RtVecStorageObj* storage = rt_vec_storage_new(4);
    rt_root_slot_store(&frame, 0, storage);

    RtVecObj* vec = (RtVecObj*)rt_alloc_obj(
        ts,
        &rt_type_vec_desc,
        sizeof(uint64_t) + sizeof(void*)
    );
    vec->len = 0;
    vec->storage = storage;

    rt_pop_roots(ts);
    return (void*)vec;
}

uint64_t rt_vec_len(const void* vec_obj) {
    const RtVecObj* vec = rt_require_vec_obj(vec_obj, "rt_vec_len: object is not Vec");
    return vec->len;
}

void rt_vec_push(void* vec_obj, void* value) {
    RtVecObj* vec = rt_require_vec_obj(vec_obj, "rt_vec_push: object is not Vec");
    rt_vec_grow_if_needed(vec);

    RtVecStorageObj* storage = vec->storage;
    rt_require(storage != NULL, "rt_vec_push: internal storage is null");
    storage->elements[vec->len] = value;
    vec->len += 1;
}

void* rt_vec_get(const void* vec_obj, uint64_t index) {
    const RtVecObj* vec = rt_require_vec_obj(vec_obj, "rt_vec_get: object is not Vec");
    if (index >= vec->len) {
        rt_panic("rt_vec_get: index out of bounds");
    }

    RtVecStorageObj* storage = vec->storage;
    rt_require(storage != NULL, "rt_vec_get: internal storage is null");
    return storage->elements[index];
}

void rt_vec_set(void* vec_obj, uint64_t index, void* value) {
    RtVecObj* vec = rt_require_vec_obj(vec_obj, "rt_vec_set: object is not Vec");
    if (index >= vec->len) {
        rt_panic("rt_vec_set: index out of bounds");
    }

    RtVecStorageObj* storage = vec->storage;
    rt_require(storage != NULL, "rt_vec_set: internal storage is null");
    storage->elements[index] = value;
}
