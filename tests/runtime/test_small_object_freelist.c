#include "runtime.h"
#include "runtime_dbg.h"

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>


typedef struct Obj32 {
    RtObjHeader header;
    uint64_t value;
} Obj32;


typedef struct Obj40 {
    RtObjHeader header;
    uint64_t left;
    uint64_t right;
} Obj40;


typedef struct Obj128 {
    RtObjHeader header;
    uint8_t payload[104];
} Obj128;


typedef struct Obj136 {
    RtObjHeader header;
    uint8_t payload[112];
} Obj136;


static const RtType OBJ32_TYPE = {
    .type_id = 401,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(Obj32),
    .debug_name = "FreelistObj32",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
};


static const RtType OBJ40_TYPE = {
    .type_id = 402,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(Obj40),
    .debug_name = "FreelistObj40",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
};


static const RtType OBJ128_TYPE = {
    .type_id = 403,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(Obj128),
    .debug_name = "FreelistObj128",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
};


static const RtType OBJ136_TYPE = {
    .type_id = 404,
    .flags = RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(Obj136),
    .debug_name = "FreelistObj136",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
};


static const RtType VARIABLE_OBJ32_TYPE = {
    .type_id = 405,
    .flags = RT_TYPE_FLAG_VARIABLE_SIZE | RT_TYPE_FLAG_LEAF,
    .abi_version = 1,
    .align_bytes = 8,
    .fixed_size_bytes = sizeof(Obj32),
    .debug_name = "FreelistVariableObj32",
    .trace_fn = NULL,
    .pointer_offsets = NULL,
    .pointer_offsets_count = 0,
    .reserved0 = 0,
    .super_type = NULL,
    .interface_tables = NULL,
    .interface_slot_count = 0,
    .reserved1 = 0,
    .class_vtable = NULL,
    .class_vtable_count = 0,
    .reserved2 = 0,
};


static void fail(const char* message) {
    fprintf(stderr, "test_small_object_freelist: %s\n", message);
    exit(1);
}


static void assert_u64_eq(uint64_t actual, uint64_t expected, const char* message) {
    if (actual != expected) {
        fprintf(
            stderr,
            "test_small_object_freelist: %s (actual=%llu expected=%llu)\n",
            message,
            (unsigned long long)actual,
            (unsigned long long)expected
        );
        exit(1);
    }
}


static void* alloc_test_obj(const RtType* type, uint64_t total_size) {
    uint64_t payload_bytes = total_size - sizeof(RtObjHeader);
    return rt_alloc_obj(rt_thread_state(), type, payload_bytes);
}


static const RtSmallObjectFreelistBucketStats* find_bucket(
    const RtSmallObjectFreelistStats* stats,
    uint64_t object_size_bytes
) {
    for (uint64_t index = 0u; index < stats->bucket_count; index++) {
        const RtSmallObjectFreelistBucketStats* bucket = &stats->buckets[index];
        if (bucket->object_size_bytes == object_size_bytes) {
            return bucket;
        }
    }
    return NULL;
}


static const RtSmallObjectFreelistBucketStats* require_bucket(
    const RtSmallObjectFreelistStats* stats,
    uint64_t object_size_bytes
) {
    const RtSmallObjectFreelistBucketStats* bucket = find_bucket(stats, object_size_bytes);
    if (bucket == NULL) {
        fail("expected small-object freelist bucket to exist");
    }
    return bucket;
}


static void assert_bucket_empty(const RtSmallObjectFreelistBucketStats* bucket, const char* context) {
    assert_u64_eq(bucket->allocation_requests, 0u, context);
    assert_u64_eq(bucket->freelist_hits, 0u, context);
    assert_u64_eq(bucket->freelist_misses, 0u, context);
    assert_u64_eq(bucket->returned_objects, 0u, context);
    assert_u64_eq(bucket->retained_objects, 0u, context);
}


static void test_bucket_table_is_reported(void) {
    RtSmallObjectFreelistStats stats = rt_gc_get_small_object_freelist_stats();
    assert_u64_eq(stats.bucket_count, RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT, "bucket count should be stable");

    const uint64_t expected_sizes[RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT] = {
        32u,
        40u,
        48u,
        64u,
        80u,
        96u,
        128u,
    };

    for (uint64_t index = 0u; index < RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT; index++) {
        assert_u64_eq(
            stats.buckets[index].object_size_bytes,
            expected_sizes[index],
            "bucket size should match the runtime size-class table"
        );
    }
}


static void test_classification_stats_without_reuse(void) {
    rt_gc_reset_state();

    Obj32* obj32 = (Obj32*)alloc_test_obj(&OBJ32_TYPE, sizeof(Obj32));
    Obj40* obj40 = (Obj40*)alloc_test_obj(&OBJ40_TYPE, sizeof(Obj40));
    Obj128* obj128 = (Obj128*)alloc_test_obj(&OBJ128_TYPE, sizeof(Obj128));
    Obj136* obj136 = (Obj136*)alloc_test_obj(&OBJ136_TYPE, sizeof(Obj136));
    Obj32* variable_obj32 = (Obj32*)alloc_test_obj(&VARIABLE_OBJ32_TYPE, sizeof(Obj32));

    if (obj32 == NULL || obj40 == NULL || obj128 == NULL || obj136 == NULL || variable_obj32 == NULL) {
        fail("unseeded allocation should keep using the fallback allocator");
    }
    if (
        obj32 == (Obj32*)obj40
        || obj32 == (Obj32*)obj128
        || obj32 == (Obj32*)obj136
        || obj32 == variable_obj32
    ) {
        fail("unseeded allocation should not reuse unrelated objects");
    }

    RtGcStats gc_stats = rt_gc_get_stats();
    assert_u64_eq(gc_stats.tracked_object_count, 5u, "all test allocations should be tracked by the GC");

    RtSmallObjectFreelistStats stats = rt_gc_get_small_object_freelist_stats();
    assert_u64_eq(stats.eligible_requests, 3u, "supported fixed-size objects should be eligible");
    assert_u64_eq(stats.variable_size_requests, 1u, "variable-size objects should not be eligible");
    assert_u64_eq(stats.unsupported_size_requests, 1u, "unsupported fixed sizes should fall back");
    assert_u64_eq(stats.fallback_allocations, 5u, "PR 4 should route every allocation through fallback");

    const RtSmallObjectFreelistBucketStats* bucket32 = require_bucket(&stats, sizeof(Obj32));
    const RtSmallObjectFreelistBucketStats* bucket40 = require_bucket(&stats, sizeof(Obj40));
    const RtSmallObjectFreelistBucketStats* bucket128 = require_bucket(&stats, sizeof(Obj128));
    const RtSmallObjectFreelistBucketStats* bucket48 = require_bucket(&stats, 48u);

    assert_u64_eq(bucket32->allocation_requests, 1u, "32-byte bucket should count one fixed-size request");
    assert_u64_eq(bucket32->freelist_hits, 0u, "PR 4 should not have freelist hits");
    assert_u64_eq(bucket32->freelist_misses, 1u, "eligible PR 4 requests should miss the not-yet-used freelist");
    assert_u64_eq(bucket32->returned_objects, 0u, "PR 4 should not return objects to freelists");
    assert_u64_eq(bucket32->retained_objects, 0u, "PR 4 should not retain objects in freelists");

    assert_u64_eq(bucket40->allocation_requests, 1u, "40-byte bucket should count one fixed-size request");
    assert_u64_eq(bucket40->freelist_misses, 1u, "40-byte bucket should report the fallback miss");

    assert_u64_eq(bucket128->allocation_requests, 1u, "128-byte bucket should count one fixed-size request");
    assert_u64_eq(bucket128->freelist_misses, 1u, "128-byte bucket should report the fallback miss");

    assert_bucket_empty(bucket48, "unused bucket should stay empty");

    rt_gc_collect();
    gc_stats = rt_gc_get_stats();
    assert_u64_eq(gc_stats.tracked_object_count, 0u, "unrooted fallback allocations should still be collectable");
}


static void test_seeded_freelist_hit_zeroes_block_and_initializes_header(void) {
    rt_gc_reset_state();

    void* unsupported_seed = rt_dbg_seed_small_object_freelist(sizeof(Obj136), 0xCCu);
    if (unsupported_seed != NULL) {
        fail("unsupported object sizes should not be seedable into a freelist bucket");
    }

    Obj32* seeded = (Obj32*)rt_dbg_seed_small_object_freelist(sizeof(Obj32), 0xA5u);
    if (seeded == NULL) {
        fail("supported object size should be seedable into a freelist bucket");
    }

    RtSmallObjectFreelistStats before_alloc = rt_gc_get_small_object_freelist_stats();
    const RtSmallObjectFreelistBucketStats* before_bucket32 = require_bucket(&before_alloc, sizeof(Obj32));
    assert_u64_eq(before_bucket32->returned_objects, 1u, "test seed should count as a returned object");
    assert_u64_eq(before_bucket32->retained_objects, 1u, "test seed should retain one object");

    Obj32* obj = (Obj32*)alloc_test_obj(&OBJ32_TYPE, sizeof(Obj32));
    if (obj != seeded) {
        fail("eligible allocation should pop a seeded block from the freelist");
    }

    if (obj->header.type != &OBJ32_TYPE) {
        fail("freelist hit should still receive normal header type initialization");
    }
    assert_u64_eq(obj->header.size_bytes, sizeof(Obj32), "freelist hit should receive normal size initialization");
    assert_u64_eq(obj->header.gc_flags, 0u, "freelist hit should receive normal GC flag initialization");
    assert_u64_eq(obj->header.reserved0, 0u, "freelist hit should receive normal reserved-field initialization");
    assert_u64_eq(obj->value, 0u, "freelist hit should be zeroed before header initialization");

    RtSmallObjectFreelistStats after_alloc = rt_gc_get_small_object_freelist_stats();
    assert_u64_eq(after_alloc.eligible_requests, 1u, "freelist hit should count as an eligible request");
    assert_u64_eq(after_alloc.fallback_allocations, 0u, "freelist hit should not call fallback allocation");
    assert_u64_eq(after_alloc.variable_size_requests, 0u, "freelist hit test should not count variable-size requests");
    assert_u64_eq(after_alloc.unsupported_size_requests, 0u, "unsupported test seeding should not count as allocation");

    const RtSmallObjectFreelistBucketStats* bucket32 = require_bucket(&after_alloc, sizeof(Obj32));
    assert_u64_eq(bucket32->allocation_requests, 1u, "freelist hit should count one bucket request");
    assert_u64_eq(bucket32->freelist_hits, 1u, "freelist hit should increment bucket hits");
    assert_u64_eq(bucket32->freelist_misses, 0u, "freelist hit should not increment bucket misses");
    assert_u64_eq(bucket32->returned_objects, 1u, "freelist hit should preserve returned-object history");
    assert_u64_eq(bucket32->retained_objects, 0u, "freelist hit should consume the retained object");

    RtGcStats gc_stats = rt_gc_get_stats();
    assert_u64_eq(gc_stats.tracked_object_count, 1u, "freelist-hit allocation should still be tracked by the GC");

    rt_gc_collect();
    gc_stats = rt_gc_get_stats();
    assert_u64_eq(gc_stats.tracked_object_count, 0u, "unrooted freelist-hit allocation should still be collectable");
}


static void test_stats_reset_with_gc_state(void) {
    rt_gc_reset_state();

    (void)alloc_test_obj(&OBJ32_TYPE, sizeof(Obj32));
    RtSmallObjectFreelistStats before_reset = rt_gc_get_small_object_freelist_stats();
    assert_u64_eq(before_reset.eligible_requests, 1u, "test setup should create one eligible request");

    rt_gc_reset_state();

    RtSmallObjectFreelistStats after_reset = rt_gc_get_small_object_freelist_stats();
    assert_u64_eq(after_reset.bucket_count, RT_SMALL_OBJECT_FREELIST_BUCKET_COUNT, "reset should preserve bucket count");
    assert_u64_eq(after_reset.eligible_requests, 0u, "reset should clear eligible request count");
    assert_u64_eq(after_reset.variable_size_requests, 0u, "reset should clear variable-size request count");
    assert_u64_eq(after_reset.unsupported_size_requests, 0u, "reset should clear unsupported-size request count");
    assert_u64_eq(after_reset.fallback_allocations, 0u, "reset should clear fallback allocation count");

    for (uint64_t index = 0u; index < after_reset.bucket_count; index++) {
        assert_bucket_empty(&after_reset.buckets[index], "reset should clear every bucket counter");
    }
}


int main(void) {
    rt_init();

    test_bucket_table_is_reported();
    test_classification_stats_without_reuse();
    test_seeded_freelist_hit_zeroes_block_and_initializes_header();
    test_stats_reset_with_gc_state();

    rt_shutdown();
    puts("test_small_object_freelist: ok");
    return 0;
}
