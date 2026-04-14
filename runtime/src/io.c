#include "io.h"

#include <stdlib.h>
#include <stdio.h>
#include <string.h>

#include "runtime.h"


static FILE* rt_file_from_handle(uint64_t file_handle, const char* api_name) {
    FILE* file = (FILE*)(uintptr_t)file_handle;
    if (file == NULL) {
        rt_panic(api_name);
    }
    return file;
}

static char* rt_copy_path_string(const void* path_u8_array_obj) {
    const uint8_t* path_bytes = (const uint8_t*)rt_array_data_ptr(path_u8_array_obj);
    const size_t path_len = (size_t)rt_array_len(path_u8_array_obj);

    char* path = (char*)malloc(path_len + 1u);
    if (path == NULL) {
        rt_panic_oom();
    }

    if (path_len > 0u) {
        memcpy(path, path_bytes, path_len);
    }
    path[path_len] = '\0';
    return path;
}

static void rt_write_all_to_file(FILE* file, const uint8_t* bytes, size_t length, const char* api_name) {
    size_t offset = 0u;
    while (offset < length) {
        const size_t written = fwrite(bytes + offset, 1u, length - offset, file);
        if (written == 0u) {
            rt_panic(api_name);
        }
        offset += written;
    }
}

uint64_t rt_file_stdin_handle(void) {
    return (uint64_t)(uintptr_t)stdin;
}

uint64_t rt_file_open_for_read(const void* path_u8_array_obj) {
    char* path = rt_copy_path_string(path_u8_array_obj);
    FILE* file = fopen(path, "rb");
    free(path);
    if (file == NULL) {
        rt_panic("rt_file_open_read: failed opening file");
    }

    return (uint64_t)(uintptr_t)file;
}

void rt_file_close(uint64_t file_handle) {
    FILE* file = rt_file_from_handle(file_handle, "rt_file_close: invalid file handle");
    if (fclose(file) != 0) {
        rt_panic("rt_file_close: failed closing file");
    }
}

uint64_t rt_file_read_u8_array(uint64_t file_handle, void* array_obj, uint64_t offset) {
    FILE* file = rt_file_from_handle(file_handle, "rt_file_read_u8_array: invalid file handle");
    const uint64_t length_u64 = rt_array_len(array_obj);
    if (offset > length_u64) {
        rt_panic("rt_file_read_u8_array: offset out of bounds");
    }

    const size_t length = (size_t)length_u64;
    const size_t start = (size_t)offset;
    const size_t remaining = length - start;
    uint8_t* bytes = (uint8_t*)rt_array_data_ptr(array_obj);

    const size_t read_count = fread(bytes + start, 1u, remaining, file);
    if (read_count == 0u && ferror(file)) {
        rt_panic("rt_file_read_u8_array: failed reading file");
    }

    return offset + (uint64_t)read_count;
}

void rt_file_write_all(const void* path_u8_array_obj, const void* value_u8_array_obj) {
    char* path = rt_copy_path_string(path_u8_array_obj);
    FILE* file = fopen(path, "wb");
    free(path);
    if (file == NULL) {
        rt_panic("rt_file_write_all: failed opening file");
    }

    const uint8_t* bytes = (const uint8_t*)rt_array_data_ptr(value_u8_array_obj);
    const size_t length = (size_t)rt_array_len(value_u8_array_obj);
    rt_write_all_to_file(file, bytes, length, "rt_file_write_all: failed writing file");

    if (fclose(file) != 0) {
        rt_panic("rt_file_write_all: failed closing file");
    }
}

uint64_t rt_write_u8_array(const void* array_obj) {
    const uint8_t* bytes = (const uint8_t*)rt_array_data_ptr(array_obj);
    const size_t length = (size_t)rt_array_len(array_obj);

    const size_t written = fwrite(bytes, 1u, length, stdout);
    if (written == 0u && ferror(stdout)) {
        rt_panic("rt_write_u8_array: failed writing stdout");
    }

    return (uint64_t)written;
}
