#ifndef NIFLHEIM_RUNTIME_IO_H
#define NIFLHEIM_RUNTIME_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void rt_write_u8_array(const void* array_obj);
void* rt_read_all_bytes(void);

#ifdef __cplusplus
}
#endif

#endif
