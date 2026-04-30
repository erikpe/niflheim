#ifndef NIFLHEIM_RUNTIME_PANIC_H
#define NIFLHEIM_RUNTIME_PANIC_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

__attribute__((noreturn)) void rt_panic(const char* message);
__attribute__((noreturn)) void rt_panic_null_deref(void);
__attribute__((noreturn)) void rt_panic_invalid_shift_count(void);
__attribute__((noreturn)) void rt_panic_bad_cast(const char* from_type, const char* to_type);
__attribute__((noreturn)) void rt_panic_oom(void);
__attribute__((noreturn)) void rt_panic_null_term_array(const void* array_obj);
__attribute__((noreturn)) void rt_panic_array_api_null_object(void);
__attribute__((noreturn)) void rt_panic_array_get_out_of_bounds(uint64_t kind_tag);
__attribute__((noreturn)) void rt_panic_array_set_out_of_bounds(uint64_t kind_tag);

#ifdef __cplusplus
}
#endif

#endif