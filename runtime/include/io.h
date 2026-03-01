#ifndef NIFLHEIM_RUNTIME_IO_H
#define NIFLHEIM_RUNTIME_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint64_t rt_write_u8_array(const void* array_obj);
uint64_t rt_read_u8_array(void* array_obj, uint64_t offset);

#ifdef __cplusplus
}
#endif

#endif
