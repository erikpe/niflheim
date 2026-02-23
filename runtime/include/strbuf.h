#ifndef NIFLHEIM_RUNTIME_STRBUF_H
#define NIFLHEIM_RUNTIME_STRBUF_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void* rt_strbuf_new(uint64_t capacity);
void rt_strbuf_reserve(void* strbuf_obj, uint64_t new_capacity);
void* rt_strbuf_from_str(const void* str_obj);
void* rt_strbuf_to_str(const void* strbuf_obj);
uint64_t rt_strbuf_len(const void* strbuf_obj);
uint8_t rt_strbuf_get_u8(const void* strbuf_obj, uint64_t index);
void rt_strbuf_set_u8(void* strbuf_obj, uint64_t index, uint8_t value);

#ifdef __cplusplus
}
#endif

#endif
