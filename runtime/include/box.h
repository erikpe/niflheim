#ifndef NIFLHEIM_RUNTIME_BOX_H
#define NIFLHEIM_RUNTIME_BOX_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void* rt_box_i64_new(int64_t value);
void* rt_box_u64_new(uint64_t value);
void* rt_box_u8_new(uint64_t value);
void* rt_box_bool_new(int64_t value);
void* rt_box_double_new(double value);

int64_t rt_box_i64_get(const void* box_obj);
uint64_t rt_box_u64_get(const void* box_obj);
uint64_t rt_box_u8_get(const void* box_obj);
int64_t rt_box_bool_get(const void* box_obj);
double rt_box_double_get(const void* box_obj);

#ifdef __cplusplus
}
#endif

#endif
