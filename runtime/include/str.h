#ifndef NIFLHEIM_RUNTIME_STR_H
#define NIFLHEIM_RUNTIME_STR_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct RtThreadState RtThreadState;

void* rt_str_from_bytes(RtThreadState* ts, const uint8_t* bytes, uint64_t len);
void* rt_str_from_char(uint8_t value);
uint64_t rt_str_len(const void* str_obj);
const uint8_t* rt_str_data_ptr(const void* str_obj);
uint8_t rt_str_get_u8(const void* str_obj, int64_t index);
void* rt_str_slice(const void* str_obj, int64_t begin, int64_t end);

#ifdef __cplusplus
}
#endif

#endif
