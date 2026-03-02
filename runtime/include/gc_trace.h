#ifndef NIFLHEIM_RUNTIME_GC_TRACE_H
#define NIFLHEIM_RUNTIME_GC_TRACE_H

#ifdef __cplusplus
extern "C" {
#endif

typedef enum RtGcTracePhase {
	RT_GC_TRACE_PHASE_MARK = 0,
	RT_GC_TRACE_PHASE_SWEEP = 1,
} RtGcTracePhase;

void rt_gc_trace_collect_begin(void);
void rt_gc_trace_phase_begin(RtGcTracePhase phase);
void rt_gc_trace_phase_end(RtGcTracePhase phase);
void rt_gc_trace_collect_end(void);
void rt_gc_trace_reset(void);
void rt_gc_trace_print_summary(void);

#ifdef __cplusplus
}
#endif

#endif