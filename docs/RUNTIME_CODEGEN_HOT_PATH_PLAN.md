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

5. Keep the default runtime ABI small.
   Leave `rt_trace_*` in the default runtime, but move root-frame compatibility helpers into a separate debug/test-only module so they stop inflating the core runtime surface.

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

Status: implemented on the current branch.

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

Status: implemented on the current branch.

Goal: keep the runtime readable after codegen stops calling the helper functions, move compatibility helpers out of the default runtime, and verify the intended performance change on the benchmark.

Files to change:

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [tests/runtime/test_roots_positive.c](../tests/runtime/test_roots_positive.c)
- [tests/runtime/test_roots_negative.c](../tests/runtime/test_roots_negative.c)
- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)

Tasks:

1. Move the former `rt_root_frame_init`, `rt_push_roots`, and `rt_pop_roots` compatibility surface into debug-only helpers.
2. Rename them to `rt_dbg_*` in a separate `runtime_dbg` module and header.
3. Update runtime root tests accordingly.
4. Rebuild and profile the benchmark to confirm the helper-call hotspots disappear.
5. Record the before/after profile delta in the patch or PR description.

Validation note on the current branch:

- the compatibility helper API lives in `runtime_dbg.h` / `runtime_dbg.c` for tests and hand-written C callers
- `make -C runtime test-all` passes
- a no-runtime-trace benchmark build of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) completes successfully with `elapsed=0.89s` and `perf stat` elapsed time of about `0.899s`
- generated assembly for the benchmark contains no `rt_root_frame_init`, `rt_push_roots`, or `rt_pop_roots` calls
- the default `libruntime.a` excludes the `rt_dbg_*` helper surface

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
8. Keep debug helper wrappers readable and aligned with the inline semantics.
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

### Implementation Task List And Estimated Patch Order

The safest way to land package 2 is as five small patches.

#### Patch 1: Make safepoints explicit in the liveness result

Goal: turn the current liveness analysis into data that can drive slot allocation without coupling layout directly to IR traversal details.

Files to change:

- [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py)
- [compiler/codegen/model.py](../compiler/codegen/model.py)
- [tests/compiler/codegen/test_root_liveness.py](../tests/compiler/codegen/test_root_liveness.py)

Tasks:

1. [x] Extend the liveness result with a compact safepoint-oriented view, not just per-node query helpers.
2. [x] Record which named reference locals are live across each GC-capable expression call, lvalue call, and lowered `for ... in` helper call.
3. [x] Keep the existing query methods intact so emitter behavior does not change in this patch.
4. [x] Add tests that assert the new safepoint summaries for straight-line code, branches, and loops.

Why this patch goes first:

- it isolates analysis changes from layout changes
- it makes later slot allocation logic easier to reason about and test independently
- it keeps the first patch behavior-preserving

Expected review size: small.

#### Patch 2: Introduce `NamedRootSlotPlan` and greedy slot reuse

Goal: compute a reusable named-root slot assignment from the safepoint data before touching stack layout.

Files to change:

- [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py)
- [compiler/codegen/model.py](../compiler/codegen/model.py)
- `compiler/codegen/root_slot_plan.py`
- [tests/compiler/codegen/test_root_liveness.py](../tests/compiler/codegen/test_root_liveness.py)
- `tests/compiler/codegen/test_root_slot_plan.py`

Tasks:

1. [x] Add a small `NamedRootSlotPlan` model that maps `LocalId` values to reusable named root-slot indices.
2. [x] Build the plan from the safepoint summaries using a greedy coloring-style pass:
   - two locals cannot share a slot if they are live at the same safepoint
   - locals with no safepoint liveness must get no named root slot
3. [x] Keep temp root slots out of this plan entirely.
4. [x] Add focused unit tests for:
   - locals that never cross a safepoint
   - locals live at disjoint safepoints
   - locals simultaneously live across the same call
   - loop-carried references that must keep a stable slot

Why this patch is separate:

- it is the core policy change for package 2
- it can be tested without changing generated assembly yet

Expected review size: medium.

#### Patch 3: Switch layout building to the slot plan

Goal: shrink function root frames by deriving named root slots from `NamedRootSlotPlan` instead of from all reference locals.

Files to change:

- [compiler/codegen/layout.py](../compiler/codegen/layout.py)
- [compiler/codegen/model.py](../compiler/codegen/model.py)
- [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py)
- [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py)

Tasks:

1. [x] Thread `NamedRootSlotPlan` into layout construction.
2. [x] Replace the current `root_slot_keys = all reference locals` rule with plan-driven root-slot indices.
3. [x] Preserve the existing temp-root allocation rules and offsets.
4. [x] Update layout tests to assert:
   - smaller `root_slot_count` when locals never cross safepoints
   - reused `root_index` values for non-overlapping locals
   - unchanged temp-root behavior

Why this patch is separate:

- it changes stack-frame shape and should be easy to review against stable analysis inputs
- it keeps generator/emitter changes minimal until the new layout is validated

Expected review size: medium.

#### Patch 4: Update codegen to use smaller named-root frames

Status: implemented on the current branch.

Goal: make the existing emitter and generator logic consume the reduced/reused named root slots correctly.

Files to change:

- [compiler/codegen/generator.py](../compiler/codegen/generator.py)
- [compiler/codegen/emitter_fn.py](../compiler/codegen/emitter_fn.py)
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [compiler/codegen/emitter_stmt.py](../compiler/codegen/emitter_stmt.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](../tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_emit_asm_calls.py](../tests/compiler/codegen/test_emit_asm_calls.py)

Tasks:

1. [x] Ensure named-root spill and clear paths consult the plan-driven `root_slot_offsets_by_local_id` values only.
2. [x] Keep temp-root call protection exactly as it works today.
3. [x] Add assembly tests showing that functions now reserve and touch fewer named root slots when liveness permits.
4. [x] Keep existing regression coverage for loops, array writes, runtime calls, and return paths.

Why this patch is separate:

- it is the first point where reduced root-slot counts become visible in emitted assembly
- separating it from layout makes regressions easier to localize

Expected review size: medium.

#### Patch 5: End-to-end validation and benchmark check

Status: implemented on the current branch.

Goal: confirm the smaller root frames are correct under GC pressure and actually reduce generated shadow-stack state on the benchmark.

Files to change:

- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)
- optionally golden metadata or test comments if any fixture needs clarification

Tasks:

1. [x] Run the focused compiler tests for liveness, layout, and root-emission behavior.
2. [x] Run `make -C runtime test-all` even though the runtime code is unchanged, because GC/rooting correctness is what this package is trying to preserve.
3. [x] Rebuild and run [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) and the `solver2` benchmark.
4. [x] Compare root-frame sizes and touched root slots in generated assembly before and after.
5. [x] Record the observed deltas in the patch or PR description.

Validation note on the current branch:

- focused compiler coverage passes, including the broader root/call/array/generator batch and the full `tests/compiler` suite (`1005 passed`)
- `make -C runtime test-all` passes
- `./scripts/golden.sh` passes (`51/51` spec files, `427` runs total)
- a no-runtime-trace profile build of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) completes successfully on `full_input` with `RESULT:20172`, `/usr/bin/time` elapsed time of about `0.94s`, and `perf stat -d` elapsed time of about `1.07s`
- a no-runtime-trace profile build of [aoc/2025/11/part2/solver2.nif](../aoc/2025/11/part2/solver2.nif) completes successfully on the full workload input with repeated `RESULT:287039700129600`, `/usr/bin/time` elapsed time of about `2.85s`, and `perf stat -d` elapsed time of about `2.74s`
- layout/assembly delta analysis against the pre-package-2 "all reference locals get dedicated named root slots" rule shows:
   - [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif): total named root slots drop from `70` to `39`, and total root-frame slots drop from `172` to `141`; the largest individual reductions are `rref` (`17` to `12` total slots), `decode_levels` (`11` to `8`), `decode_button` (`11` to `8`), and `swap_rows` (`2` to `0`)
   - [aoc/2025/11/part2/solver2.nif](../aoc/2025/11/part2/solver2.nif): total named root slots drop from `29` to `11`, and total root-frame slots drop from `77` to `59`; the main hot path `run` drops from `20` total root-frame slots to `11`
- flat `perf report` output for both workloads is now dominated by runtime GC/tracked-set/allocation work (`rt_tracked_set_find_slot`, `rt_gc_collect`, allocator internals, and `Map` operations), which is consistent with package 2 reducing shadow-stack footprint without introducing a new codegen-side hotspot

Why this patch goes last:

- it keeps measurement and documentation separate from mechanism changes
- it makes the previous four patches easier to review as code-only changes

Expected review size: small.

### Recommended Review And Landing Sequence

Use this exact sequence:

1. Land patch 1 by itself.
2. Land patch 2 and review the slot-allocation policy independently of layout.
3. Land patch 3 and rerun `test_layout.py` plus `test_root_liveness.py`.
4. Land patch 4 and rerun the focused codegen suite.
5. Land patch 5 only after benchmark and GC-correctness checks are complete.

### Package 2 Execution Checklist

1. [x] Extend `NamedRootLiveness` with safepoint-oriented summaries.
2. [x] Add a `NamedRootSlotPlan` model and a greedy slot allocator.
3. [x] Add dedicated unit tests for slot planning.
4. [x] Thread the slot plan into [compiler/codegen/layout.py](../compiler/codegen/layout.py).
5. [x] Update layout tests to assert smaller root frames and reused slots.
6. [x] Update generator and emitter code to use the reduced root-slot mapping without changing temp-root behavior.
7. [x] Extend assembly tests to assert fewer named root slots are touched when liveness permits.
8. [x] Run the focused compiler tests for liveness, layout, and root emission.
9. [x] Run `make -C runtime test-all`.
10. [x] Re-run the benchmark workloads and record the generated root-frame and timing deltas.

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
4. [x] Run the focused compiler suite:
   `pytest tests/compiler/codegen/test_root_liveness.py tests/compiler/codegen/test_layout.py tests/compiler/codegen/test_emit_asm_runtime_roots.py`
5. [x] Run golden tests that stress loops, method calls, array writes, and constructors.
6. [x] Re-run [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) and the original `solver2` workload to confirm both performance and GC correctness.

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

### Implementation Task List And Estimated Patch Order

The safest way to land package 3 is as three small patches plus one optional follow-up.

#### Patch 1: Add tracking-pool observability and lock in tests

Status: implemented on the current branch.

Goal: create a small measurement and test surface for tracked-node reuse before changing allocation behavior.

Files to change:

- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/Makefile](../runtime/Makefile)
- `tests/runtime/test_gc_tracking_pool.c`
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)

Tasks:

1. [x] Add a tiny stats/debug surface for tracked-node allocation behavior, for example pool hits, pool misses, chunk allocations, and nodes returned.
2. [x] Keep that surface runtime-local and opt-in so normal callers do not have to know about pooling internals.
3. [x] Add a focused runtime test that can assert reuse once pooling exists, even if the first patch still reports zero hits.
4. [x] Keep this patch behavior-preserving.

Validation note on the current branch:

- the new tracking-pool stats surface lives in [runtime/include/gc.h](../runtime/include/gc.h) and [runtime/src/gc.c](../runtime/src/gc.c)
- the focused runtime regression lives in `tests/runtime/test_gc_tracking_pool.c`
- `make -C runtime test-all` passes with the new test included

Why this patch goes first:

- it gives later pooling changes a concrete assertion surface
- it keeps the first review small and mostly diagnostic
- it reduces the chance of arguing about performance improvements without measurement hooks

Expected review size: small.

#### Patch 2: Introduce pooled `RtTrackedObject` allocation

Status: implemented on the current branch.

Goal: replace one-`malloc`-per-tracking-node allocation with a chunked free-list while leaving object payload allocation alone.

Files to change:

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/gc.h](../runtime/include/gc.h)
- `tests/runtime/test_gc_tracking_pool.c`
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)

Tasks:

1. [x] Add a free-list for `RtTrackedObject` nodes.
2. [x] Add chunk allocation when the free-list is empty instead of calling `malloc(sizeof(RtTrackedObject))` for every tracked object.
3. [x] Keep the tracked-object linked-list semantics unchanged so mark/sweep traversal logic does not have to be redesigned.
4. [x] Route `rt_gc_track_allocation` through the new pool allocator.
5. [x] Update the new runtime test so it proves the pool is actually being exercised.

Validation note on the current branch:

- tracked-node allocation now uses a chunk-backed free-list in [runtime/src/gc.c](../runtime/src/gc.c)
- `tests/runtime/test_gc_tracking_pool.c` now asserts observable pool hits and chunk refill behavior
- `make -C runtime test-gc-tracking-pool` and `make -C runtime test-all` pass

Why this patch is separate:

- it is the core mechanism change for package 3
- it can be reviewed without mixing in sweep-policy or intrusive-layout changes
- it limits the correctness surface to allocation and bookkeeping, not collection semantics

Expected review size: medium.

#### Patch 3: Return nodes to the pool during sweep and validate benchmark impact

Status: implemented on the current branch.

Goal: complete the reuse loop by recycling tracked nodes during collection and reset paths, then measure the end-to-end effect.

Files to change:

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/Makefile](../runtime/Makefile)
- `tests/runtime/test_gc_tracking_pool.c`
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)
- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)

Tasks:

1. [x] Return swept `RtTrackedObject` nodes to the pool instead of freeing them immediately.
2. [x] Make `rt_gc_reset_state` and any test-only reset path release pooled chunks cleanly so the runtime does not leak memory across test processes.
3. [x] Tighten tests so repeated allocate/sweep cycles with a stable live set show reuse instead of steady node allocation churn.
4. [x] Re-run the benchmark and compare `_int_malloc`, `_int_free`, and `rt_gc_track_allocation` flat samples against the package 2 baseline.
5. [x] Record the before/after benchmark note in the patch or PR description.

Validation note on the current branch:

- swept tracked nodes are now returned to the free-list in [runtime/src/gc.c](../runtime/src/gc.c), and `rt_gc_reset_state` still releases pooled chunks cleanly
- `tests/runtime/test_gc_tracking_pool.c` now proves post-collection reuse without requiring new chunk allocations, and [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c) now covers repeated allocate/collect cycles with stable chunk usage
- `make -C runtime test-gc-tracking-pool`, `make -C runtime test`, and `make -C runtime test-all` pass
- a no-runtime-trace profile build of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) completes successfully with `RESULT:20172`, `/usr/bin/time` elapsed time of about `0.80s`, and `perf stat -d` elapsed time of about `0.80s`
- compared with the package 2 baseline on the same workload, allocator-side flat samples move materially in the expected direction:
   - `_int_free`: about `5.10%` to about `2.49%`
   - `_int_malloc`: about `4.58%` to about `1.36%`
   - `rt_gc_track_allocation`: now visible at about `2.18%`, but still below the tracked-set and collection hotspots
- the remaining top flat samples are still `rt_tracked_set_find_slot.constprop.0` and `rt_gc_collect`, which is consistent with package 3 reducing tracked-node allocation churn without changing the tracked-set or collector algorithms yet

Why this patch goes last in stage 1:

- recycling on sweep is where correctness bugs are most likely to hide
- keeping measurement in the same patch makes it obvious whether the completed pool moved the hotspot enough
- it keeps cleanup informed by the actual final mechanism rather than by scaffolding assumptions

Expected review size: medium.

#### Patch 4: Optional intrusive metadata follow-up only if pooling is insufficient

Goal: remove the separate `RtTrackedObject` node type entirely, but only if stage 1 pooling still leaves tracked-node overhead materially visible.

Files to change:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)
- `tests/runtime/test_gc_tracking_pool.c`

Tasks:

1. Add intrusive GC list linkage to `RtObjHeader`.
2. Remove the separate tracked-node allocation path and update mark/sweep traversal accordingly.
3. Add structure-layout and reset-path assertions so the new object-header contract stays explicit.
4. Re-run the full runtime suite and benchmark validation again before deciding whether the extra complexity is justified.

Why this patch is optional and last:

- it changes core runtime object layout rather than staying local to GC bookkeeping
- it is harder to revert and easier to get subtly wrong than stage 1 pooling
- the document's intended path is to stop after pooling if the profile has already moved enough

Expected review size: medium to large.

### Recommended Review And Landing Sequence

Use this exact sequence:

1. Land patch 1 by itself.
2. Land patch 2 and rerun the new pool-focused runtime tests plus `test_gc_stress.c`.
3. Land patch 3 and rerun `make -C runtime test-all`, then re-profile the benchmark.
4. Only do patch 4 if the package 3 profile still shows tracked-node allocation overhead as a significant remaining hotspot.

### Package 3 Execution Checklist

1. [x] Add a minimal tracked-node pool stats surface.
2. [x] Add `tests/runtime/test_gc_tracking_pool.c`.
3. [x] Route `rt_gc_track_allocation` through a pooled tracked-node allocator.
4. [x] Recycle tracked nodes during sweep and reset-state paths.
5. [x] Extend runtime stress coverage for repeated allocate/sweep cycles.
6. [x] Run `make -C runtime test-all`.
7. [x] Rebuild [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) with `NIF_PROFILE_BUILD=1` and `--omit-runtime-trace`.
8. [x] Compare `_int_malloc`, `_int_free`, and `rt_gc_track_allocation` against the package 2 baseline.
9. Stop after stage 1 if the tracked-node hotspot moves enough; only then consider intrusive metadata.

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

### Implementation Task List And Estimated Patch Order

The safest way to land package 5 is as four small patches.

#### Patch 1: Add probe observability and lock in churn-heavy tests

Status: implemented on the current branch.

Goal: create a small measurement and regression surface for tracked-set probe behavior before changing the fast path.

Files to change:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c)
- [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h)
- [runtime/Makefile](../runtime/Makefile)
- [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c)
- `tests/runtime/test_tracked_set_probe_behavior.c`

Tasks:

1. [x] Add an opt-in debug or stats surface for tracked-set probe counts or probe-depth totals.
2. [x] Keep the default non-debug fast path behavior unchanged in this patch.
3. [x] Add a focused churn-heavy runtime test that performs repeated insert, contains, and remove cycles and records expected membership behavior.
4. [x] Keep [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c) as the existing correctness anchor.
5. [x] Make this patch behavior-preserving apart from the new observability hooks and tests.

Validation note on the current branch:

- the tracked-set probe stats surface now lives in [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h) and [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c), and remains disabled unless a caller opts in explicitly
- the new churn-heavy regression lives in `tests/runtime/test_tracked_set_probe_behavior.c`
- [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c) remains the existing tombstone correctness anchor
- `make -C runtime test-tracked-set-tombstones test-tracked-set-probe-behavior test-all` passes

Why this patch goes first:

- it gives later fast-path edits a concrete assertion surface
- it keeps the first review mostly diagnostic and easy to reason about
- it reduces the chance of arguing about probe improvements without comparable measurements

Expected review size: small.

#### Patch 2: Split lookup and insertion probing into operation-specific helpers

Status: implemented on the current branch.

Goal: simplify the hot loop by replacing the generic `rt_tracked_set_find_slot` path with smaller helpers that match the actual operations.

Files to change:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c)
- [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h)
- [runtime/src/gc.c](../runtime/src/gc.c)
- `tests/runtime/test_tracked_set_probe_behavior.c`
- [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c)

Tasks:

1. [x] Replace the current generic probe helper with one helper for existing-entry lookup and one helper for insertion-slot selection with tombstone reuse.
2. [x] Introduce a tiny local probe-result struct only if it keeps call sites and the loop state simpler than multiple out-parameters.
3. [x] Update tracked-set callers so insert, contains, and remove each use the narrower helper they actually need.
4. [x] Keep current resize and rebuild policy unchanged in this patch so the review focuses on helper splitting only.
5. [x] Extend the new probe-behavior test to cover all three operation paths against the refactored helpers.

Validation note on the current branch:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c) now uses separate helper paths for existing-entry lookup and insertion-slot selection, with a tiny local probe-result struct keeping the call sites explicit
- the tracked-set public operations now record probe stats at the call sites that correspond to their dedicated helper path instead of routing through a single mode-driven probe helper
- `tests/runtime/test_tracked_set_probe_behavior.c` now covers per-operation counter separation, duplicate insert behavior, and the existing churn-heavy workload
- `make -C runtime test-tracked-set-tombstones test-tracked-set-probe-behavior test-all` passes

Why this patch is separate:

- it is the core hot-loop simplification for package 5
- it can be reviewed independently of tombstone policy changes
- isolating the helper split makes correctness regressions easier to localize

Expected review size: medium.

#### Patch 3: Tighten tombstone-heavy rebuild policy and compact earlier

Status: implemented on the current branch.

Goal: reduce wasted probing under churn-heavy workloads once the fast path is split into operation-specific helpers.

Files to change:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c)
- [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c)
- `tests/runtime/test_tracked_set_probe_behavior.c`
- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)

Tasks:

1. [x] Add an earlier rebuild or compact trigger for tombstone-dominated tables even when total occupancy is still below the normal growth threshold.
2. [x] Keep the policy small and explicit so the compaction rule remains easy to audit.
3. [x] Add test coverage or debug assertions that reinsertion preserves every live member across rebuild and compact paths.
4. [x] Extend the churn-heavy probe test so it exercises the new compaction trigger under repeated remove and reinsert cycles.
5. [x] Re-run the runtime suite and record whether the tracked-set flat hotspot moves in the expected direction.

Validation note on the current branch:

- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c) now applies a scratch-buffer tombstone compaction pass when tombstones dominate the live set and cross a small minimum threshold, while preserving the existing grow path and occupancy-driven rebuild path
- the tracked-set probe stats surface now records total maintenance passes and tombstone-triggered compactions so tests can prove the new policy is exercised explicitly
- `tests/runtime/test_tracked_set_probe_behavior.c` now covers a repeated churn workload that triggers tombstone compaction each round and a focused reinsertion case that proves live members survive compaction while removed members stay absent
- `make -C runtime test-tracked-set-tombstones test-tracked-set-probe-behavior test-all` passes
- `./scripts/golden.sh --filter 'aoc/2025/10/part2/**' --print-per-run` passes again after replacing the earlier heap-allocating same-capacity rebuild with the scratch-buffer compaction path
- a no-runtime-trace profile build of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) completes successfully with `RESULT:20172`, `/usr/bin/time` elapsed time of about `0.73s`, and `perf stat -d` elapsed time of about `0.73s`
- compared with the post-package-3 baseline on the same workload, tracked-set flat cost moves in the expected direction:
   - `rt_tracked_set_lookup_existing`: about `16.23%` for the old monolithic probe helper to about `7.08%`
   - `rt_gc_collect`: about `11.22%` to about `11.68%`
   - `_int_free`: about `2.49%` to about `3.57%`
   - `_int_malloc`: about `1.36%` to about `1.50%`
   - the new scratch-buffer compaction helper support `rt_tracked_set_rehash_live_entries` is visible at about `2.25%`

Why this patch is separate:

- tombstone policy is the most behavior-sensitive part of package 5
- keeping it separate from the helper split makes regressions much easier to diagnose
- it allows the benchmark delta to be attributed to compaction policy rather than to mechanical refactoring

Expected review size: medium.

#### Patch 4: Validation, benchmark check, and documentation update

Status: implemented on the current branch.

Goal: confirm the tracked-set changes stay correct under GC pressure and actually reduce tracked-set flat cost on the benchmark.

Files to change:

- [docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md](../docs/RUNTIME_CODEGEN_HOT_PATH_PLAN.md)
- optionally test comments or runtime test notes if a fixture needs clarification

Tasks:

1. [x] Run the focused tracked-set runtime tests, including the tombstone regression and the new churn-heavy probe test.
2. [x] Run `make -C runtime test-all`.
3. [x] Rebuild and run [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) with `NIF_PROFILE_BUILD=1` and `--omit-runtime-trace`.
4. [x] Compare the flat profile for the tracked-set helpers against the post-package-3 baseline.
5. [x] Record the before or after timing and flat-profile note in this plan document or the eventual patch description.

Validation note on the current branch:

- `make -C runtime test-tracked-set-tombstones test-tracked-set-probe-behavior` passes
- `make -C runtime test-all` passes
- `./scripts/golden.sh --filter 'aoc/2025/10/part2/**' --print-per-run` passes
- a no-runtime-trace profile build of [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) completes successfully with `RESULT:20172`, `/usr/bin/time` elapsed time of about `0.73s`, and `perf stat -d` elapsed time of about `0.73s`
- compared with the post-package-3 baseline on the same workload, the tracked-set flat hotspot moves materially in the intended direction:
   - `rt_tracked_set_lookup_existing`: about `16.23%` for the old monolithic probe helper to about `7.08%`
   - `rt_gc_collect`: about `11.22%` to about `11.68%`
   - `_int_free`: about `2.49%` to about `3.57%`
   - `_int_malloc`: about `1.36%` to about `1.50%`
   - `rt_tracked_set_rehash_live_entries`: about `2.25%`
- the tracked-set path is now no longer dominated by the old monolithic probe helper, and the remaining visible cost is split across collection, lookup, and the new compaction maintenance path

Why this patch goes last:

- it keeps measurement and documentation separate from the mechanism changes
- it makes the earlier patches easier to review as code-only changes
- it prevents benchmark notes from getting stale while the implementation is still moving

Expected review size: small.

### Recommended Review And Landing Sequence

Use this exact sequence:

1. Land patch 1 by itself.
2. Land patch 2 and rerun the focused tracked-set tests.
3. Land patch 3 and rerun `make -C runtime test-all`, then re-profile the benchmark.
4. Land patch 4 only after the benchmark confirms the tracked-set hotspot moved enough to justify stopping.

### Package 5 Execution Checklist

1. [x] Add an opt-in tracked-set probe stats surface.
2. [x] Add `tests/runtime/test_tracked_set_probe_behavior.c`.
3. [x] Split generic probing into lookup-specific and insertion-specific helpers.
4. [x] Keep tracked-set call sites explicit about whether they need lookup, insertion, or tombstone reuse.
5. [x] Tighten tombstone-heavy rebuild or compact policy.
6. [x] Extend churn-heavy runtime coverage for repeated insert, contains, and remove cycles.
7. [x] Run `make -C runtime test-all`.
8. [x] Rebuild [tests/golden/aoc/2025/10/part2/test_solver.nif](../tests/golden/aoc/2025/10/part2/test_solver.nif) with `NIF_PROFILE_BUILD=1` and `--omit-runtime-trace`.
9. [x] Compare the tracked-set flat-profile samples against the post-package-3 baseline and record the result.

### Testing Checklist

1. [x] Keep [tests/runtime/test_tracked_set_tombstones.c](../tests/runtime/test_tracked_set_tombstones.c) as the core regression test.
2. [x] Add a runtime test that performs repeated insert/remove/contains cycles with heavy tombstone creation and asserts termination plus expected membership results.
3. [x] Add a test or debug-only assertion that rebuild/compact logic preserves all live members after reinsertion.
4. [x] Run `make -C runtime test-all`.
5. [x] Re-run the benchmark and compare `rt_tracked_set_find_slot` replacement functions in the flat profile.

### Follow-Up Test Plan

The current package-5 coverage is good enough to ship, but it is still lighter than ideal in a few places. The most useful follow-up tests are:

1. [x] Add a runtime integration test that exercises tracked-set maintenance through real traced objects, not just synthetic zeroed `RtObjHeader` arrays.
   Implemented on the current branch as `tests/runtime/test_tracked_set_gc_integration.c`.
   Coverage shape:
   - allocate objects with reference fields and a real `RtType.pointer_offsets` layout
   - force repeated `rt_gc_collect()` calls while alternating insert, remove, and reinsertion patterns
   - assert that rooted graphs survive compaction and that unrooted graphs are reclaimed

2. [x] Add a focused runtime test for the occupancy-driven same-capacity maintenance path, not just the tombstone-dominated compaction path.
   Implemented on the current branch as `tests/runtime/test_tracked_set_occupancy_rebuild.c`.
   Coverage shape:
   - occupancy-triggered maintenance fires without a grow
   - all live members remain reachable after the maintenance pass
   - removed members stay absent

3. [x] Add a deterministic runtime test for wrap-around probe chains and tombstone reuse ordering.
   Implemented on the current branch as `tests/runtime/test_tracked_set_probe_clusters.c`.
   Coverage shape:
   - construct a small test-only key set that lands in the same probe cluster
   - verify lookup across wrap-around
   - verify insertion prefers the first tombstone before a later `NULL`
   - verify removal does not break later lookups in the same cluster

4. [x] Add a compiler/runtime integration pytest that stresses tracked-set maintenance indirectly through forced GC and reference churn.
   Implemented on the current branch as `tests/compiler/integration/test_cli_semantic_codegen_runtime/test_tracked_set_gc_churn.py`.
   Coverage shape:
   - compile and run a small NIF program that allocates many short-lived reference objects in loops
   - call `rt_gc_collect()` repeatedly between aliasing, nulling, and reinsertion steps
   - assert stable program output under default and `--omit-runtime-trace` builds

5. [x] Add a small golden regression that exercises tracked-set churn without relying on the large AOC benchmark.
   Implemented on the current branch as `tests/golden/runtime/tracked_set_churn/test_tracked_set_churn.nif` and `tests/golden/runtime/tracked_set_churn/test_tracked_set_churn_spec.yaml`.
   Coverage shape:
   - a compact language-level program that creates repeated GC pressure with reference objects and alias churn
   - expected output that proves live references survived while dead ones were reclaimed

These follow-up tests are not required to consider package 5 complete, but they would make future tracked-set changes safer by covering the runtime table mechanics, the GC integration boundary, and a smaller language-level regression path.

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