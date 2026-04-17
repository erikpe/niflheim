#ifndef NIFLHEIM_RUNTIME_IO_H
#define NIFLHEIM_RUNTIME_IO_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

uint64_t rt_file_stdin_handle(void);
uint64_t rt_file_open_for_read(const void* path_u8_array_obj);
uint64_t rt_file_try_open_for_read(const void* path_u8_array_obj);
void rt_file_close(uint64_t file_handle);
uint64_t rt_file_read_u8_array(uint64_t file_handle, void* array_obj, uint64_t offset);
void rt_file_write_all(const void* path_u8_array_obj, const void* value_u8_array_obj);
uint64_t rt_write_u8_array(const void* array_obj);

#ifdef __cplusplus
}
#endif

#endif
