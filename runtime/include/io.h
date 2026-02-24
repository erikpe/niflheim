#ifndef NIFLHEIM_RUNTIME_IO_H
#define NIFLHEIM_RUNTIME_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

void rt_println_i64(int64_t value);
void rt_println_u64(uint64_t value);
void rt_println_u8(uint64_t value);
void rt_println_bool(int64_t value);
void rt_println_double(double value);

#ifdef __cplusplus
}
#endif

#endif
