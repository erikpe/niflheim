#include "gc_trace.h"
#include "gc.h"

#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>


static int g_gc_trace_enabled = -1;
static int g_gc_summary_registered = 0;
static int g_gc_summary_emitted = 0;

typedef struct RtGcTraceTotals {
    uint64_t cycle_count;
    uint64_t timing_start_ns;
    uint64_t total_collect_ns;
    uint64_t total_mark_ns;
    uint64_t total_sweep_ns;
} RtGcTraceTotals;

typedef struct RtGcTraceCycle {
    uint64_t index;
    RtGcStats before;
    uint64_t collect_start_ns;
    uint64_t mark_start_ns;
    uint64_t mark_end_ns;
    uint64_t sweep_start_ns;
    uint64_t sweep_end_ns;
} RtGcTraceCycle;

static RtGcTraceTotals g_totals = {0};
static RtGcTraceCycle g_cycle = {0};


static uint64_t rt_saturating_add_u64(uint64_t a, uint64_t b) {
    if (UINT64_MAX - a < b) {
        return UINT64_MAX;
    }
    return a + b;
}


static uint64_t rt_time_now_ns_impl(void) {
    struct timespec ts;
    if (timespec_get(&ts, TIME_UTC) != TIME_UTC) {
        return 0;
    }
    uint64_t sec_ns = rt_saturating_add_u64((uint64_t)ts.tv_sec, 0u);
    if (sec_ns > UINT64_MAX / 1000000000u) {
        return UINT64_MAX;
    }
    sec_ns *= 1000000000u;
    return rt_saturating_add_u64(sec_ns, (uint64_t)ts.tv_nsec);
}


static uint64_t rt_ms_whole_from_ns(uint64_t ns) {
    return ns / 1000000u;
}


static uint64_t rt_ms_frac3_from_ns(uint64_t ns) {
    return (ns / 1000u) % 1000u;
}


static uint64_t rt_pct_basis_points(uint64_t part, uint64_t whole) {
    if (whole == 0u) {
        return 0u;
    }
    long double scaled = ((long double)part * 10000.0L) / (long double)whole;
    if (scaled <= 0.0L) {
        return 0u;
    }
    if (scaled >= (long double)UINT64_MAX) {
        return UINT64_MAX;
    }
    return (uint64_t)scaled;
}


static uint64_t rt_pct_whole_from_bps(uint64_t bps) {
    return bps / 100u;
}


static uint64_t rt_pct_frac2_from_bps(uint64_t bps) {
    return bps % 100u;
}


static uint64_t rt_duration_or_zero(uint64_t end_ns, uint64_t start_ns) {
    if (end_ns < start_ns) {
        return 0u;
    }
    return end_ns - start_ns;
}


static void rt_gc_trace_summary_atexit(void) {
    if (g_gc_summary_emitted) {
        return;
    }
    if (g_totals.cycle_count == 0u || g_totals.timing_start_ns == 0u) {
        return;
    }
    rt_gc_trace_print_summary();
}


static int rt_gc_trace_is_enabled(void) {
    if (g_gc_trace_enabled >= 0) {
        return g_gc_trace_enabled;
    }

    const char* value = getenv("NIF_GC_TRACE");
    if (value == NULL || value[0] == '\0' || value[0] == '0') {
        g_gc_trace_enabled = 0;
    } else {
        g_gc_trace_enabled = 1;
        if (!g_gc_summary_registered) {
            g_gc_summary_registered = 1;
            (void)atexit(rt_gc_trace_summary_atexit);
        }
    }
    return g_gc_trace_enabled;
}


void rt_gc_trace_collect_begin(void) {
    g_cycle = (RtGcTraceCycle){0};
    g_cycle.index = g_totals.cycle_count + 1u;
    g_cycle.before = rt_gc_get_stats();

    if (!rt_gc_trace_is_enabled()) {
        return;
    }

    g_cycle.collect_start_ns = rt_time_now_ns_impl();
    if (g_totals.timing_start_ns == 0u) {
        g_totals.timing_start_ns = g_cycle.collect_start_ns;
    }

    fprintf(
        stderr,
        "[gc] cycle=%" PRIu64 " phase=start"
        " alloc=%" PRIu64 "B"
        " live=%" PRIu64 "B"
        " tracked=%" PRIu64 "obj"
        " threshold=%" PRIu64 "B\n",
        g_cycle.index,
        g_cycle.before.allocated_bytes,
        g_cycle.before.live_bytes,
        g_cycle.before.tracked_object_count,
        g_cycle.before.next_gc_threshold
    );
}


void rt_gc_trace_phase_begin(RtGcTracePhase phase) {
    if (!rt_gc_trace_is_enabled()) {
        return;
    }
    const uint64_t now_ns = rt_time_now_ns_impl();
    switch (phase) {
        case RT_GC_TRACE_PHASE_MARK:
            g_cycle.mark_start_ns = now_ns;
            break;
        case RT_GC_TRACE_PHASE_SWEEP:
            g_cycle.sweep_start_ns = now_ns;
            break;
        default:
            break;
    }
}


void rt_gc_trace_phase_end(RtGcTracePhase phase) {
    if (!rt_gc_trace_is_enabled()) {
        return;
    }
    const uint64_t now_ns = rt_time_now_ns_impl();
    switch (phase) {
        case RT_GC_TRACE_PHASE_MARK:
            g_cycle.mark_end_ns = now_ns;
            break;
        case RT_GC_TRACE_PHASE_SWEEP:
            g_cycle.sweep_end_ns = now_ns;
            break;
        default:
            break;
    }
}


void rt_gc_trace_collect_end(void) {
    g_totals.cycle_count = g_cycle.index;

    if (!rt_gc_trace_is_enabled()) {
        return;
    }

    RtGcStats after_stats = rt_gc_get_stats();

    const uint64_t collected_bytes = (g_cycle.before.allocated_bytes >= after_stats.live_bytes)
        ? (g_cycle.before.allocated_bytes - after_stats.live_bytes)
        : 0u;
    const uint64_t collected_objects = (g_cycle.before.tracked_object_count >= after_stats.tracked_object_count)
        ? (g_cycle.before.tracked_object_count - after_stats.tracked_object_count)
        : 0u;

    const uint64_t mark_ns = rt_duration_or_zero(g_cycle.mark_end_ns, g_cycle.mark_start_ns);
    const uint64_t sweep_ns = rt_duration_or_zero(g_cycle.sweep_end_ns, g_cycle.sweep_start_ns);
    const uint64_t collect_ns = rt_duration_or_zero(g_cycle.sweep_end_ns, g_cycle.collect_start_ns);

    g_totals.total_mark_ns = rt_saturating_add_u64(g_totals.total_mark_ns, mark_ns);
    g_totals.total_sweep_ns = rt_saturating_add_u64(g_totals.total_sweep_ns, sweep_ns);
    g_totals.total_collect_ns = rt_saturating_add_u64(g_totals.total_collect_ns, collect_ns);

    fprintf(
        stderr,
        "[gc] cycle=%" PRIu64 " phase=end"
        " alloc=%" PRIu64 "B->%" PRIu64 "B"
        " live=%" PRIu64 "B->%" PRIu64 "B"
        " tracked=%" PRIu64 "obj->%" PRIu64 "obj"
        " threshold=%" PRIu64 "B->%" PRIu64 "B"
        " reclaim=%" PRIu64 "B"
        " freed=%" PRIu64 "obj\n",
        g_cycle.index,
        g_cycle.before.allocated_bytes,
        after_stats.allocated_bytes,
        g_cycle.before.live_bytes,
        after_stats.live_bytes,
        g_cycle.before.tracked_object_count,
        after_stats.tracked_object_count,
        g_cycle.before.next_gc_threshold,
        after_stats.next_gc_threshold,
        collected_bytes,
        collected_objects
    );
}


void rt_gc_trace_print_summary(void) {
    if (g_gc_summary_emitted) {
        return;
    }
    if (!rt_gc_trace_is_enabled()) {
        return;
    }
    if (g_totals.cycle_count == 0u || g_totals.timing_start_ns == 0u) {
        g_gc_summary_emitted = 1;
        fprintf(
            stderr,
            "[gc] summary cycles=0 wall=0.000ms"
            " total_collect=0.000ms(0.00%%) total_mark=0.000ms(0.00%%)"
            " total_sweep=0.000ms(0.00%%) outside_gc=0.000ms(0.00%%)\n"
        );
        return;
    }

    uint64_t now_ns = rt_time_now_ns_impl();
    uint64_t total_window_ns = rt_duration_or_zero(now_ns, g_totals.timing_start_ns);
    uint64_t outside_gc_ns = 0u;
    if (total_window_ns >= g_totals.total_collect_ns) {
        outside_gc_ns = total_window_ns - g_totals.total_collect_ns;
    }

    const uint64_t wall_ms_whole = rt_ms_whole_from_ns(total_window_ns);
    const uint64_t wall_ms_frac = rt_ms_frac3_from_ns(total_window_ns);
    const uint64_t collect_ms_whole = rt_ms_whole_from_ns(g_totals.total_collect_ns);
    const uint64_t collect_ms_frac = rt_ms_frac3_from_ns(g_totals.total_collect_ns);
    const uint64_t mark_ms_whole = rt_ms_whole_from_ns(g_totals.total_mark_ns);
    const uint64_t mark_ms_frac = rt_ms_frac3_from_ns(g_totals.total_mark_ns);
    const uint64_t sweep_ms_whole = rt_ms_whole_from_ns(g_totals.total_sweep_ns);
    const uint64_t sweep_ms_frac = rt_ms_frac3_from_ns(g_totals.total_sweep_ns);
    const uint64_t outside_ms_whole = rt_ms_whole_from_ns(outside_gc_ns);
    const uint64_t outside_ms_frac = rt_ms_frac3_from_ns(outside_gc_ns);

    const uint64_t collect_bps = rt_pct_basis_points(g_totals.total_collect_ns, total_window_ns);
    const uint64_t mark_bps = rt_pct_basis_points(g_totals.total_mark_ns, total_window_ns);
    const uint64_t sweep_bps = rt_pct_basis_points(g_totals.total_sweep_ns, total_window_ns);
    const uint64_t outside_bps = rt_pct_basis_points(outside_gc_ns, total_window_ns);

    fprintf(
        stderr,
        "[gc] summary cycles=%" PRIu64 " wall=%" PRIu64 ".%03" PRIu64 "ms"
        " total_collect=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " total_mark=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " total_sweep=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)"
        " outside_gc=%" PRIu64 ".%03" PRIu64 "ms(%" PRIu64 ".%02" PRIu64 "%%)\n",
        g_totals.cycle_count,
        wall_ms_whole,
        wall_ms_frac,
        collect_ms_whole,
        collect_ms_frac,
        rt_pct_whole_from_bps(collect_bps),
        rt_pct_frac2_from_bps(collect_bps),
        mark_ms_whole,
        mark_ms_frac,
        rt_pct_whole_from_bps(mark_bps),
        rt_pct_frac2_from_bps(mark_bps),
        sweep_ms_whole,
        sweep_ms_frac,
        rt_pct_whole_from_bps(sweep_bps),
        rt_pct_frac2_from_bps(sweep_bps),
        outside_ms_whole,
        outside_ms_frac,
        rt_pct_whole_from_bps(outside_bps),
        rt_pct_frac2_from_bps(outside_bps)
    );
    g_gc_summary_emitted = 1;
}


void rt_gc_trace_reset(void) {
    g_gc_trace_enabled = -1;
    g_totals = (RtGcTraceTotals){0};
    g_cycle = (RtGcTraceCycle){0};
    g_gc_summary_emitted = 0;
}