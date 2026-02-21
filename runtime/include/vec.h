#ifndef NIFLHEIM_RUNTIME_VEC_H
#define NIFLHEIM_RUNTIME_VEC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void* rt_vec_new(void);
uint64_t rt_vec_len(const void* vec_obj);
void rt_vec_push(void* vec_obj, void* value);
void* rt_vec_get(const void* vec_obj, uint64_t index);
void rt_vec_set(void* vec_obj, uint64_t index, void* value);

#ifdef __cplusplus
}
#endif

#endif
