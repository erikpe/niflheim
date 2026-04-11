# Runtime And Codegen Hot Path Plan

Status: proposed.

This document turns the recent benchmark profiling work into a concrete implementation plan for a small set of runtime and compiler changes that are likely to produce real end-to-end speedups while staying readable and maintainable.

The plan is grounded in the profile of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif), especially the no-runtime-trace run. That workload is useful because it is allocation-heavy, loop-heavy, and call-heavy without depending on benchmark-only tricks.

The primary goals are:

- reduce shadow-stack overhead in ordinary reference-heavy code
- reduce unnecessary root-slot footprint in generated code
- reduce per-object allocator and tracking overhead in the runtime
- keep each change independently testable and revertible
- avoid large architectural rewrites unless a smaller staged change fails to move the benchmark

## Implementation Rules

Use these rules for every work package in this document:

1. Keep each package independently shippable.
2. Prefer one small mechanism change over a broad redesign.
3. Preserve existing runtime semantics and ABI unless the package explicitly says otherwise.
4. Add focused regression tests before or with the implementation.
5. Re-measure the benchmark after every package instead of batching multiple runtime changes together.
6. Keep debugability: do not remove assertions or safety checks unless the replacement still fails loudly on corrupted state.

## Ordered Checklist

1. Inline shadow-stack push/pop in generated assembly.
2. Reuse named root slots and shrink function root frames.
3. Pool tracked-object metadata, and only consider intrusive metadata if pooling is not enough.
4. Add small-object freelists for common fixed-size allocations.
5. Split and simplify the tracked-set probe fast path.

## 1. Inline Shadow-Stack Push/Pop In Generated Assembly

### Why This Is Worth Doing

The no-trace profile shows a large amount of time in `rt_root_frame_init`, `rt_push_roots`, and `rt_pop_roots`. Those helpers are very small and the compiler already knows the exact frame and slot addresses at codegen time.

Inlining the mechanics into generated assembly removes call overhead without changing the shadow-stack model.

### What To Change

Primary files:

- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [compiler/codegen/layout.py](../compiler/codegen/layout.py)
- [compiler/codegen/model.py](../compiler/codegen/model.py)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_generator.py](../tests/compiler/codegen/test_generator.py)

Recommended new helper module:

- `compiler/codegen/abi/runtime_layout.py`

### Concrete Plan

1. Add a single compiler-side source of truth for `RtThreadState` and `RtRootFrame` field offsets.
   The compiler currently hardcodes stack layout but does not name runtime-struct offsets explicitly. Add a tiny module with constants for `RtThreadState.roots_top`, `RtRootFrame.prev`, `RtRootFrame.slot_count`, `RtRootFrame.reserved`, and `RtRootFrame.slots`.

2. Keep root-slot zeroing in codegen, not in the runtime helper.
   [compiler/codegen/generator.py](../compiler/codegen/generator.py) already zeros named root slots and temp root slots through `emit_zero_slots`. Preserve that behavior and stop depending on `rt_root_frame_init` for zeroing.

3. Replace `emit_root_frame_setup` call-outs with direct stores.
   In [compiler/codegen/generator.py](../compiler/codegen/generator.py), change `emit_root_frame_setup` so it:
   - calls `rt_thread_state`
   - stores the thread-state pointer in the function frame as today
   - writes `frame->prev = ts->roots_top`
   - writes `frame->slot_count = root_count`
   - writes `frame->reserved = 0`
   - writes `frame->slots = &first_root_slot`
   - writes `ts->roots_top = &frame`

4. Inline root popping in both epilogue paths.
   Update `emit_function_epilogue` and `emit_ref_epilogue` in [compiler/codegen/generator.py](../compiler/codegen/generator.py) to restore `ts->roots_top = frame->prev` directly instead of calling `rt_pop_roots`.

5. Keep the runtime helpers temporarily as debug-compatible wrappers.
   Leave `rt_root_frame_init`, `rt_push_roots`, and `rt_pop_roots` in [runtime/src/runtime.c](../runtime/src/runtime.c) for runtime tests and non-codegen callers, but stop emitting them from compiled code. Remove them only if they become truly unused.

6. Preserve trace ordering.
   Existing tests assert that roots are pushed before `rt_trace_push`. Keep that ordering exactly the same in the generated assembly.

### Implementation Task List And Estimated Patch Order

The safest way to land package 1 is as four small patches.

#### Patch 1: Introduce explicit runtime-layout constants and lock in tests

Status: implemented on the current branch.

Goal: create one compiler-side place for runtime struct offsets before changing emitted assembly.

Files to change:

- `compiler/codegen/abi/runtime_layout.py`
- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_generator.py](../tests/compiler/codegen/test_generator.py)

Tasks:

1. Add constants for `RtThreadState.roots_top` and `RtRootFrame` field offsets.
2. Refactor [compiler/codegen/generator.py](../compiler/codegen/generator.py) to reference those constants, even if the emitted assembly is still unchanged.
3. Add or tighten tests that describe the current root setup ordering and helper-call presence.
4. Keep this patch behavior-preserving.

Why this patch goes first:

- it reduces risk in later codegen edits
- it gives the inline implementation one shared offset source instead of ad hoc immediates
- it produces a clean review diff with no semantic change

Expected review size: small.

#### Patch 2: Inline root-frame setup in function and constructor prologues

Status: implemented on the current branch.

Goal: remove `rt_root_frame_init` and `rt_push_roots` calls from generated code while keeping the same shadow-stack semantics.

Files to change:

- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py)

Tasks:

1. Rewrite `emit_root_frame_setup` in [compiler/codegen/generator.py](../compiler/codegen/generator.py) to emit direct field stores.
2. Preserve the current `rt_thread_state` call and thread-state spill location.
3. Ensure the compiler still sets `slot_count`, `reserved`, and `slots` on the frame before publishing it to `ts->roots_top`.
4. Keep root-slot zeroing where it is today.
5. Update codegen tests to assert inline stores instead of helper calls.
6. Keep ordering checks that prove roots are visible before `rt_trace_push`.

Why this patch is separate:

- prologue setup is the largest part of the mechanism change
- constructors and normal functions both pass through the same helper, so this patch exercises the shared path cleanly
- isolating setup from epilogue changes makes debugging much easier if GC safety regresses

Expected review size: medium.

#### Patch 3: Inline root popping in both epilogues

Goal: remove `rt_pop_roots` calls from generated returns without changing return-value preservation.

Files to change:

- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_generator.py](../tests/compiler/codegen/test_generator.py)

Tasks:

1. Update `emit_function_epilogue` to load `frame->prev` and restore `ts->roots_top` directly.
2. Update `emit_ref_epilogue` the same way.
3. Preserve the existing `rax` and `xmm0` save/restore behavior around epilogue work.
4. Preserve current trace-pop ordering.
5. Extend tests that currently mention `call rt_pop_roots` so they assert the new inline restore sequence instead.
6. Re-run root-heavy codegen tests to confirm return-value handling did not regress.

Why this patch is separate:

- epilogue code has more ABI sensitivity than prologue setup
- separating it keeps the failure surface smaller if return registers are accidentally clobbered

Expected review size: small to medium.

#### Patch 4: Runtime cleanup, compatibility wrappers, and benchmark validation

Goal: keep the runtime readable after codegen stops calling the helper functions, and verify the intended performance change on the benchmark.

Files to change:

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [tests/runtime/test_roots_positive.c](../tests/runtime/test_roots_positive.c)
- [tests/runtime/test_roots_negative.c](../tests/runtime/test_roots_negative.c)
- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)

Tasks:

1. Decide whether `rt_root_frame_init`, `rt_push_roots`, and `rt_pop_roots` remain public wrappers or become runtime-internal test helpers.
2. If they remain public, keep their implementations simple and obviously equivalent to the new inline code path.
3. If any signature or visibility changes are needed, update runtime root tests accordingly.
4. Rebuild and profile the benchmark to confirm the helper-call hotspots disappear.
5. Record the before/after profile delta in the patch or PR description.

Why this patch goes last:

- it avoids mixing mechanism changes with cleanup
- it keeps runtime tests usable throughout the rollout
- it ensures cleanup is informed by actual benchmark results

Expected review size: small.

### Recommended Review And Landing Sequence

Use this exact sequence:

1. Land patch 1 by itself.
2. Land patch 2 and rerun the focused codegen suite plus runtime root tests.
3. Land patch 3 and rerun the same suites, then re-profile the benchmark.
4. Land patch 4 only after the profile confirms the expected hotspot moved.

### Package 1 Execution Checklist

1. Create `compiler/codegen/abi/runtime_layout.py` with named offset constants.
2. Refactor [compiler/codegen/generator.py](../compiler/codegen/generator.py) to consume those constants.
3. Update tests to describe current behavior before changing emitted assembly.
4. Inline prologue root-frame setup in [compiler/codegen/generator.py](../compiler/codegen/generator.py).
5. Update constructor and function root setup assertions in [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py).
6. Inline epilogue root popping in [compiler/codegen/generator.py](../compiler/codegen/generator.py).
7. Re-run codegen tests that exercise root setup, epilogues, and return preservation.
8. Keep runtime helper wrappers readable and aligned with the inline semantics.
9. Run `make -C runtime test-all`.
10. Re-profile [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) and verify the helper-call hotspots are gone.

### Testing Checklist

1. Extend [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py) to assert that reference-heavy functions no longer emit `call rt_root_frame_init`, `call rt_push_roots`, or `call rt_pop_roots`.
2. Add assertions for the exact inline stores to `roots_top`, `prev`, `slot_count`, and `slots`.
3. Keep existing ordering assertions for root setup relative to `rt_trace_push` and `rt_trace_pop`.
4. Run the focused codegen suite:
   `pytest tests/compiler/codegen/test_emit_asm_runtime_roots.py tests/compiler/codegen/test_generator.py tests/compiler/codegen/test_layout.py`
5. Run runtime correctness coverage:
   `make -C runtime test-all`
6. Rebuild and rerun the benchmark workload with and without `--omit-runtime-trace` to confirm the flat profile no longer contains those helper calls.

### Exit Criteria

- No compiled function with roots emits helper calls for frame push/pop.
- Existing root correctness tests still pass.
- The benchmark shows a measurable reduction in shadow-stack overhead.

## 2. Better Root-Slot Reuse And Smaller Root Frames

### Why This Is Worth Doing

The current layout builder gives every reference-typed local a dedicated named root slot for the whole function. That is simple, but it over-allocates shadow-stack state and makes every rooted function pay for dead or non-overlapping references.

The compiler already has liveness analysis in [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py). The maintainable next step is to use that analysis to allocate fewer named root slots, not to invent a more complex GC protocol.

### What To Change

Primary files:

- [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py)
- [compiler/codegen/layout.py](../compiler/codegen/layout.py)
- [compiler/codegen/model.py](../compiler/codegen/model.py)
- [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py)
- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [tests/compiler/codegen/test_root_liveness.py](../tests/compiler/codegen/test_root_liveness.py)
- [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)

### Concrete Plan

1. Define a `NamedRootSlotPlan` stage between liveness and stack layout.
   This should be a small compiler-side data structure that says which locals actually need named root slots and which slot index each one uses.

2. Only allocate named root slots for locals that are live across a GC-capable operation.
   Use the existing liveness queries in [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py) for statement, expression-call, lvalue-call, and `for ... in` helper safepoints. A reference local that is never live across a safepoint should not consume a named root slot.

3. Reuse named root slots for non-overlapping locals.
   Start with a simple, maintainable strategy:
   - build the set of safepoints in the function
   - record which locals are live at each safepoint
   - assign slots greedily so two locals can share a slot if they are never live at the same safepoint

4. Keep temp root slots separate from named root slots.
   Do not merge the temp-root mechanism into the named-root allocator in the same change. Temp roots protect intermediate values during runtime calls and should remain a distinct concept.

5. Update layout generation to size the root frame from the slot plan instead of from all reference locals.
   That change belongs in [compiler/codegen/layout.py](../compiler/codegen/layout.py), where `root_slot_keys` and `root_slot_count` are currently derived directly from all reference-typed locals.

6. Preserve existing spill/clear behavior.
   The emitted code should still clear temp root slots and still move named roots into the correct root slot offsets. The change is slot count and slot reuse, not the meaning of roots.

### Testing Checklist

1. Add unit coverage in [tests/compiler/codegen/test_root_liveness.py](../tests/compiler/codegen/test_root_liveness.py) for locals that are:
   - reference-typed but never live across a safepoint
   - live across distinct non-overlapping safepoints
   - simultaneously live across the same call inside loops and branches
2. Add layout assertions in [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py) that verify:
   - reduced `root_slot_count`
   - reused `root_index` values for non-overlapping locals
   - stable temp-root layout
3. Extend [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py) to assert that generated functions use fewer root slots when liveness permits.
4. Run the focused compiler suite:
   `pytest tests/compiler/codegen/test_root_liveness.py tests/compiler/codegen/test_layout.py tests/compiler/codegen/test_emit_asm_runtime_roots.py`
5. Run golden tests that stress loops, method calls, array writes, and constructors.
6. Re-run [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) and the original `solver2` workload to confirm both performance and GC correctness.

### Exit Criteria

- Functions with dead or non-overlapping reference locals produce smaller root frames.
- Existing GC-safety behavior is preserved.
- The benchmark shows reduced `rt_root_frame_init`-equivalent work and less root scanning.

## 3. Pool Or Inline Tracked-Object Metadata

### Why This Is Worth Doing

Every object allocation currently performs a separate `malloc(sizeof(RtTrackedObject))` in [runtime/src/gc.c](../runtime/src/gc.c). That means one runtime object allocation turns into two native allocations: one for the object payload and one for the tracking list node.

The maintainable first step is to pool tracking nodes. Making tracking intrusive in `RtObjHeader` can remain a second-stage option only if the pool still leaves too much overhead.

### What To Change

Primary files for stage 1:

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/Makefile](../runtime/Makefile)
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)

Recommended new tests:

- `tests/runtime/test_gc_tracking_pool.c`

Optional stage 2 files if intrusive metadata is still needed:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/src/gc.c](../runtime/src/gc.c)

### Concrete Plan

1. Implement a free-list or slab for `RtTrackedObject` nodes inside [runtime/src/gc.c](../runtime/src/gc.c).
   A simple version is enough:
   - maintain a singly linked free list of unused tracking nodes
   - allocate nodes in chunks when the free list is empty
   - return nodes to the free list during sweep instead of calling `free(node)` immediately

2. Keep object payload allocation unchanged in this package.
   Do not combine this change with small-object freelists. This package should only remove the extra metadata allocation churn.

3. Add lightweight debug counters.
   Record pool hits, pool misses, and chunk allocations behind a debug or stats-only interface so benchmark runs can verify the pool is actually being exercised.

4. Re-measure before deciding on intrusive metadata.
   If the pool removes most of the `_int_malloc` and `_int_free` overhead attributable to tracking nodes, stop here.

5. Only if needed, implement intrusive tracking as a separate follow-up.
   If profiling still shows tracking-node overhead is substantial, add a `gc_next` pointer to `RtObjHeader` in [runtime/include/runtime.h](../runtime/include/runtime.h) and remove the separate `RtTrackedObject` node type. Do not land this in the same patch as pooling.

### Testing Checklist

1. Add a runtime unit test that allocates many small objects, forces multiple collections, and asserts tracking-node reuse is exercised.
2. Extend [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c) or add a sibling test for repeated allocate/sweep cycles with stable live-set size.
3. Run the runtime suite:
   `make -C runtime test-all`
4. Re-run the benchmark and compare flat samples for `_int_malloc`, `_int_free`, and `rt_gc_track_allocation`.
5. If intrusive metadata is implemented later, add structure-layout assertions and rerun all runtime tests again.

### Exit Criteria

- Tracking-node native allocation traffic drops sharply.
- GC correctness is unchanged.
- The implementation remains local to the GC rather than spreading special cases throughout the runtime.

## 4. Small-Object Freelists

### Why This Is Worth Doing

The benchmark constructs many short-lived tiny objects such as `Rat`, and runtime allocation still bottoms out in zeroed heap allocation in [runtime/src/runtime.c](../runtime/src/runtime.c). A small freelist for the most common fixed-size object sizes is a practical way to cut allocator overhead without redesigning GC.

### What To Change

Primary files:

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [runtime/Makefile](../runtime/Makefile)
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)

Recommended new tests:

- `tests/runtime/test_small_object_freelist.c`

### Concrete Plan

1. Add a tiny allocator layer for fixed-size GC objects.
   Keep it narrow:
   - enable it only for a small set of size classes, for example 16, 24, 32, 48, 64, and 96 bytes total object size
   - skip variable-size objects and large objects
   - keep `calloc` as the fallback path

2. Route object allocation through that layer from `rt_try_alloc_zeroed` in [runtime/src/runtime.c](../runtime/src/runtime.c).
   On a freelist hit, pop a block, zero it, and return it. On a miss, fall back to the current allocator.

3. Return freed objects to the freelist during sweep in [runtime/src/gc.c](../runtime/src/gc.c).
   The free path already has the object header and `size_bytes`. Use that to map the object back to its freelist bucket.

4. Add a hard cap per freelist bucket.
   This keeps the implementation maintainable and prevents the runtime from silently hoarding too much memory after bursty benchmarks.

5. Keep the policy data-driven and small.
   Put bucket sizes, maximum retained nodes, and eligibility logic in one runtime-local block rather than scattering them across allocation and GC code.

### Testing Checklist

1. Add a runtime test that allocates and frees many objects in one supported size class and verifies freelist reuse through counters.
2. Add a mixed-size test that confirms unsupported sizes still use the fallback allocator path correctly.
3. Run `make -C runtime test-all`.
4. Re-run the benchmark and inspect reductions in `_int_malloc`, `_int_free`, and `rt_alloc_obj` self time.
5. Run at least one large golden workload after this change because allocator reuse bugs often survive unit tests but fail under sustained GC pressure.

### Exit Criteria

- Small fixed-size objects are frequently recycled from freelists.
- Unsupported or variable-size objects still behave exactly as before.
- Memory retention remains bounded and easy to reason about.

## 5. Tracked-Set Fast-Path Cleanup

### Why This Is Worth Doing

After the tombstone-fix work, [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c) is correct, but it is still a visible flat hotspot. The easiest maintainable improvements here are fast-path simplifications, not a wholesale data-structure replacement.

### What To Change

Primary files:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c)
- [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/Makefile](../runtime/Makefile)
- [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c)

Recommended new tests:

- `tests/runtime/test_tracked_set_probe_behavior.c`

### Concrete Plan

1. Split the current generic probe helper into operation-specific helpers.
   The current `rt_tracked_set_find_slot` serves insert, contains, and remove. Replace it with two simpler helpers:
   - one for lookup of an existing object
   - one for selecting an insertion slot with tombstone reuse

2. Add a tiny probe-result struct if needed.
   If both insert and lookup need to return more than one value, use a small local struct instead of pushing more state through pointer out-parameters.

3. Tighten rebuild policy around tombstones.
   Keep the current correctness fix, but compact earlier when tombstones dominate even if total occupied capacity is still below the growth threshold.

4. Keep hash and mask operations inline and branch-light.
   Avoid adding abstractions that obscure the hot loop. This file should stay short and mechanical.

5. Add optional probe counters under a debug compile flag.
   Average probes per insert, contains, and remove are useful when deciding whether a later redesign is warranted.

### Testing Checklist

1. Keep [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c) as the core regression test.
2. Add a runtime test that performs repeated insert/remove/contains cycles with heavy tombstone creation and asserts termination plus expected membership results.
3. Add a test or debug-only assertion that rebuild/compact logic preserves all live members after reinsertion.
4. Run `make -C runtime test-all`.
5. Re-run the benchmark and compare `rt_tracked_set_find_slot` replacement functions in the flat profile.

### Exit Criteria

- Probe behavior stays correct under churn-heavy workloads.
- The tracked-set code remains easy to audit.
- The benchmark shows a measurable drop in tracked-set flat overhead.

## Recommended Rollout Order

Land these packages in the same order as the checklist at the top of the document.

That order is intentional:

1. Inline shadow-stack setup removes avoidable helper-call overhead without changing semantics.
2. Root-slot reuse shrinks the amount of shadow-stack state the compiler produces.
3. Tracked-object pooling removes one extra native allocation per managed object.
4. Small-object freelists target the remaining native allocation cost for the object payload itself.
5. Tracked-set cleanup is easiest to evaluate after the allocation and root-management noise has already been reduced.

## Benchmark Validation Protocol

After every work package, run the same validation flow so results stay comparable.

1. Run the focused unit tests for the touched area.
2. Run `make -C runtime test-all` if any runtime code changed.
3. Rebuild [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) with `NIF_PROFILE_BUILD=1` and `--omit-runtime-trace`.
4. Collect:
   - wall-clock timing
   - GC trace summary
   - `perf stat -d`
   - `perf record/report` flat view
5. Compare the new run against the previous baseline before moving to the next package.
6. Keep a short note in the commit or PR description stating which hotspot moved and which did not.

## Non-Goals For This Plan

This document does not cover:

- escape analysis or stack allocation of user-visible objects
- unboxed value-type lowering for small classes such as `Rat`
- collector redesign or moving-GC work
- benchmark-specific source rewrites to make [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) itself faster

Those may be worthwhile later, but they are intentionally outside this first implementation plan because they are larger and riskier than the packages above.