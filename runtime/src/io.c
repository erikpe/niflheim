#include "io.h"

#include <inttypes.h>
#include <stdio.h>

void rt_println_i64(int64_t value) {
    printf("%" PRId64 "\n", value);
}

void rt_println_u64(uint64_t value) {
    printf("%" PRIu64 "\n", value);
}

void rt_println_u8(uint64_t value) {
    const uint8_t narrowed = (uint8_t)value;
    printf("%" PRIu8 "\n", narrowed);
}

void rt_println_bool(int64_t value) {
    printf("%s\n", value != 0 ? "true" : "false");
}

void rt_println_double(double value) {
    printf("%f\n", value);
}
