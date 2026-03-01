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

uint64_t rt_read_u8_array(void* array_obj, uint64_t offset) {
    const uint64_t length_u64 = rt_array_len(array_obj);
    if (offset > length_u64) {
        rt_panic("rt_read_u8_array: offset out of bounds");
    }

    const size_t length = (size_t)length_u64;
    const size_t start = (size_t)offset;
    const size_t remaining = length - start;
    uint8_t* bytes = (uint8_t*)rt_array_data_ptr(array_obj);

    const size_t read_count = fread(bytes + start, 1u, remaining, stdin);
    if (read_count == 0u && ferror(stdin)) {
        rt_panic("rt_read_u8_array: failed reading stdin");
    }

    return offset + (uint64_t)read_count;
}
