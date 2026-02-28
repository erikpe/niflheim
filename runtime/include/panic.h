#ifndef NIFLHEIM_RUNTIME_PANIC_H
#define NIFLHEIM_RUNTIME_PANIC_H

#ifdef __cplusplus
extern "C" {
#endif

__attribute__((noreturn)) void rt_panic(const char* message);
__attribute__((noreturn)) void rt_panic_null_deref(void);
__attribute__((noreturn)) void rt_panic_bad_cast(const char* from_type, const char* to_type);
__attribute__((noreturn)) void rt_panic_oom(void);
__attribute__((noreturn)) void rt_panic_null_term_array(const void* array_obj);

#ifdef __cplusplus
}
#endif

#endif