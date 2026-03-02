#ifndef NIFLHEIM_RUNTIME_GC_TRACE_H
#define NIFLHEIM_RUNTIME_GC_TRACE_H

#ifdef __cplusplus
extern "C" {
#endif

void rt_gc_trace_collect_begin(void);
void rt_gc_trace_mark_begin(void);
void rt_gc_trace_mark_end(void);
void rt_gc_trace_sweep_begin(void);
void rt_gc_trace_sweep_end(void);
void rt_gc_trace_collect_end(void);
void rt_gc_trace_reset(void);
void rt_gc_trace_print_summary(void);

#ifdef __cplusplus
}
#endif

#endif