#include "runtime.h"

#include <stdio.h>
#include <stdlib.h>

static void rt_print_stacktrace(void) {
    RtThreadState* ts = rt_thread_state();
    if (ts->trace_size == 0u || ts->trace_frames == NULL) {
        return;
    }

    fprintf(stderr, "stacktrace:\n");
    for (uint32_t index = ts->trace_size; index > 0u; index--) {
        const RtTraceFrame* frame = &ts->trace_frames[index - 1u];
        const char* function_name = frame->function_name ? frame->function_name : "<unknown>";
        const char* file_path = frame->file_path ? frame->file_path : "<unknown>";
        fprintf(stderr, "  at %s (%s:%u:%u)\n", function_name, file_path, frame->line, frame->column);
    }
}

static __attribute__((noreturn)) void rt_abort_with_message(const char* message) {
    RtThreadState* ts = rt_thread_state();

    fprintf(stderr, "panic: %s\n", message ? message : "unknown");
    if (ts->trace_size > 0u && ts->trace_frames != NULL) {
        const RtTraceFrame* top = &ts->trace_frames[ts->trace_size - 1u];
        const char* file_path = top->file_path ? top->file_path : "<unknown>";
        fprintf(stderr, "location: %s:%u:%u\n", file_path, top->line, top->column);
    }
    rt_print_stacktrace();
    abort();
}

void rt_panic(const char* message) {
    rt_abort_with_message(message);
}

void rt_panic_null_deref(void) {
    rt_panic("null dereference");
}

void rt_panic_bad_cast(const char* from_type, const char* to_type) {
    char message[256];
    snprintf(
        message,
        sizeof(message),
        "bad cast (%s -> %s)",
        from_type ? from_type : "<unknown>",
        to_type ? to_type : "<unknown>"
    );
    rt_abort_with_message(message);
}

void rt_panic_null_term_array(const void* array_obj) {
    if (array_obj == NULL) {
        rt_panic("rt_panic_null_term_array: object is null");
    }

    const char* message = (const char*)rt_array_data_ptr(array_obj);
    if (message == NULL) {
        rt_panic("rt_panic_null_term_array: array data pointer is null");
    }
    rt_panic(message);
}

void rt_panic_oom(void) {
    rt_panic("out of memory");
}