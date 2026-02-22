#ifndef NIFLHEIM_RUNTIME_STR_H
#define NIFLHEIM_RUNTIME_STR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtThreadState RtThreadState;

void* rt_str_from_bytes(RtThreadState* ts, const uint8_t* bytes, uint64_t len);
uint64_t rt_str_len(const void* str_obj);
uint64_t rt_str_get_u8(const void* str_obj, uint64_t index);
void* rt_str_slice(const void* str_obj, uint64_t begin, uint64_t end);

#ifdef __cplusplus
}
#endif

#endif
