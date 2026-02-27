#ifndef NIFLHEIM_RUNTIME_ARRAY_H
#define NIFLHEIM_RUNTIME_ARRAY_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void* rt_array_new_i64(uint64_t len);
void* rt_array_new_u64(uint64_t len);
void* rt_array_new_u8(uint64_t len);
void* rt_array_new_bool(uint64_t len);
void* rt_array_new_double(uint64_t len);
void* rt_array_new_ref(uint64_t len);

uint64_t rt_array_len(const void* array_obj);

int64_t rt_array_get_i64(const void* array_obj, uint64_t index);
uint64_t rt_array_get_u64(const void* array_obj, uint64_t index);
uint64_t rt_array_get_u8(const void* array_obj, uint64_t index);
int64_t rt_array_get_bool(const void* array_obj, uint64_t index);
double rt_array_get_double(const void* array_obj, uint64_t index);
void* rt_array_get_ref(const void* array_obj, uint64_t index);

void rt_array_set_i64(void* array_obj, uint64_t index, int64_t value);
void rt_array_set_u64(void* array_obj, uint64_t index, uint64_t value);
void rt_array_set_u8(void* array_obj, uint64_t index, uint64_t value);
void rt_array_set_bool(void* array_obj, uint64_t index, int64_t value);
void rt_array_set_double(void* array_obj, uint64_t index, double value);
void rt_array_set_ref(void* array_obj, uint64_t index, void* value);

void* rt_array_slice_i64(const void* array_obj, uint64_t start, uint64_t end);
void* rt_array_slice_u64(const void* array_obj, uint64_t start, uint64_t end);
void* rt_array_slice_u8(const void* array_obj, uint64_t start, uint64_t end);
void* rt_array_slice_bool(const void* array_obj, uint64_t start, uint64_t end);
void* rt_array_slice_double(const void* array_obj, uint64_t start, uint64_t end);
void* rt_array_slice_ref(const void* array_obj, uint64_t start, uint64_t end);

#ifdef __cplusplus
}
#endif

#endif
