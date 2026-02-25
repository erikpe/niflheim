#include "io.h"

#include <inttypes.h>
#include <stdlib.h>
#include <stdio.h>

#include "runtime.h"
#include "str.h"

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

void* rt_read_all(void) {
    size_t capacity = 4096;
    size_t len = 0;
    uint8_t* buffer = (uint8_t*)malloc(capacity);
    if (buffer == NULL) {
        rt_panic("rt_read_all: out of memory");
    }

    while (1) {
        if (len == capacity) {
            size_t new_capacity = capacity * 2;
            if (new_capacity < capacity) {
                free(buffer);
                rt_panic("rt_read_all: input too large");
            }
            uint8_t* grown = (uint8_t*)realloc(buffer, new_capacity);
            if (grown == NULL) {
                free(buffer);
                rt_panic("rt_read_all: out of memory");
            }
            buffer = grown;
            capacity = new_capacity;
        }

        const size_t remaining = capacity - len;
        const size_t read_count = fread(buffer + len, 1, remaining, stdin);
        len += read_count;

        if (read_count == 0) {
            if (ferror(stdin)) {
                free(buffer);
                rt_panic("rt_read_all: failed reading stdin");
            }
            break;
        }
    }

    RtThreadState* ts = rt_thread_state();
    void* str_obj = rt_str_from_bytes(ts, buffer, (uint64_t)len);
    free(buffer);
    return str_obj;
}
