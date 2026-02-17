#include "runtime.h"

void rt_gc_collect(RtThreadState* ts);

void rt_gc_collect(RtThreadState* ts) {
    (void)ts;
    // TODO: implement mark-sweep collector.
}
