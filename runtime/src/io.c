#include "io.h"

#include <stdlib.h>
#include <stdio.h>

#include "runtime.h"

uint64_t rt_write_u8_array(const void* array_obj) {
    const uint8_t* bytes = (const uint8_t*)rt_array_data_ptr(array_obj);
    const size_t length = (size_t)rt_array_len(array_obj);

    const size_t written = fwrite(bytes, 1u, length, stdout);
    if (written == 0u && ferror(stdout)) {
        rt_panic("rt_write_u8_array: failed writing stdout");
    }

    return (uint64_t)written;
}

void* rt_read_all_bytes(void) {
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

    void* bytes_obj = rt_array_from_bytes_u8(buffer, (uint64_t)len);
    free(buffer);
    return bytes_obj;
}
