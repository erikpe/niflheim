# GC And Allocation Fast-Path Plan

Status: PR 3 implemented.

This document turns the next recommended runtime work into an ordered implementation plan. The goal is not to tune one benchmark program by hand. The goal is to make the compiler plus runtime produce and execute more efficient code for allocation-heavy, reference-heavy programs.

The plan covers three related changes:

1. Add an exact-GC fast mode that stops validating every marked reference through the tracked-object hash set.
2. Demote the tracked-object hash set out of the default production allocation and sweep fast paths where possible.
3. Add bounded small-object freelists for common fixed-size GC object allocations.

The current profile of `aoc/2025/11/part2/solver2.nif` with `--omit-runtime-trace` is dominated by:

- `rt_gc_collect`
- `rt_tracked_set_lookup_existing`
- `rt_gc_tracked_set_insert`
- libc allocator work (`_int_malloc`, `__libc_calloc`, `_int_free`, `malloc_consolidate`)
- `rt_gc_track_allocation`
- `Map` and `Str` library code

The runtime already has exact roots and type metadata. The next practical win is to make the production collector trust that exact metadata instead of paying tracked-set validation cost on the hottest paths.

## Implementation Rules

1. Keep each PR independently shippable and benchmarkable.
2. Preserve the current debug/testing ability to catch bogus roots and invalid object references.
3. Do not change language semantics.
4. Do not combine tracked-set demotion and object freelists in one patch.
5. Keep fallback paths simple: if a new fast path cannot handle an allocation, it must fall back to the current `calloc`/`free` behavior.
6. Record benchmark deltas after every behavior-changing PR.

## Current Runtime Shape

Important files:

- [runtime/src/gc.c](../runtime/src/gc.c)
  - owns global object tracking, root marking, sweep, threshold updates, and GC stats
  - `rt_mark_ref_slot` calls `rt_as_tracked_object`, which currently validates candidates through the tracked set before marking
  - `rt_gc_track_allocation` inserts every allocation into both the linked object list and the tracked set
  - `rt_sweep_unmarked` removes dead objects from the tracked set and then calls `free(obj)`
- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c)
  - owns the object membership hash set and tombstone/compaction behavior
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - `rt_alloc_obj` computes total size, maybe collects, calls `rt_try_alloc_zeroed`, initializes the header, and tracks the object
  - `rt_try_alloc_zeroed` currently uses `calloc`, retries after GC, then returns the object
- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - defines `RtObjHeader`, `RtType`, GC flags, and runtime object layout
- [runtime/include/gc.h](../runtime/include/gc.h)
  - exposes current GC stats and tracking-pool stats
- [runtime/include/gc_tracked_set.h](../runtime/include/gc_tracked_set.h)
  - exposes tracked-set operations and probe stats
- [scripts/build.sh](../scripts/build.sh)
  - links runtime sources directly into benchmark binaries and already supports extra C flags through `NIF_CC_ARGS`

## Ordered PR Plan

## PR 1: Add GC Fast-Mode And Validation-Mode Plumbing

### Purpose

Create an explicit runtime policy switch before changing behavior. The runtime should have a default fast mode and a validation mode that keeps the current tracked-set membership checks available for tests, debugging, and benchmark comparisons.

### What To Do

- Add a small GC mode surface in [runtime/include/gc.h](../runtime/include/gc.h) and [runtime/src/gc.c](../runtime/src/gc.c).
- Prefer a compile-time macro first, for example:
  - default: `NIF_GC_VALIDATE_TRACKED_SET=0`
  - validation/debug: `NIF_GC_VALIDATE_TRACKED_SET=1`
- Optionally add a runtime stats field that reports whether validation was compiled in.
- Keep all current marking, allocation, and sweep behavior unchanged in this PR.
- Add helper predicates in `gc.c` so later PRs can branch through named functions rather than scattering preprocessor checks.
- Document how to build validation mode with `NIF_CC_ARGS`, for example:

```bash
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" ./scripts/build.sh ...
```

### Where

- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)
- [tests/runtime/test_tracked_set_gc_integration.c](../tests/runtime/test_tracked_set_gc_integration.c)
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Runtime tests still pass with default fast-mode compile settings.
- Runtime tests still pass with `NIF_GC_VALIDATE_TRACKED_SET=1`.
- Existing tracked-set tests remain meaningful and do not depend on the default collector mode.

### How To Test

```bash
make -C runtime test-all
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" make -C runtime clean test-all
NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_current --omit-runtime-trace
perf stat -d ./build/solver2_perf_current < aoc/2025/11/part2/input.txt
```

### Checklist

- [x] Add compile-time GC validation mode macro.
- [x] Add named helper predicates in `gc.c`.
- [x] Expose mode/stat information if useful for tests.
- [x] Prove default runtime tests still pass.
- [x] Prove validation-mode runtime tests still pass.
- [x] Record baseline no-trace benchmark numbers before behavior changes.

## PR 2: Fast Exact Marking Without Tracked-Set Lookup

### Purpose

Stop paying a hash-table lookup for every candidate reference during marking in the default runtime mode. The collector should trust compiler-emitted exact roots and runtime type metadata in fast mode, while validation mode keeps the old membership check.

### What To Do

- Split `rt_as_tracked_object` in [runtime/src/gc.c](../runtime/src/gc.c) into two clearly named paths:
  - validation path: current `rt_gc_tracked_set_contains(candidate)` behavior
  - fast path: treat non-null root/reference slots as object pointers and mark through the header
- Keep validation mode as the safety oracle for tests and debugging.
- Add cheap sanity checks only if they are effectively free and do not reintroduce a hash lookup. Candidates:
  - `candidate->type != NULL`
  - optional `RtType.abi_version == 1`
  - optional object-header magic only if added in a separate follow-up
- Be conservative about root contents:
  - generated code should only expose exact reference slots
  - C tests using debug root helpers should continue to run in validation mode
- Do not remove the tracked set yet. This PR only removes mark-time lookup from the default path.

### Where

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h), only if a header sanity field is added
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)
- [tests/runtime/test_array_runtime.c](../tests/runtime/test_array_runtime.c)
- [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime)
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Normal runtime suite passes in fast mode.
- Validation-mode runtime suite passes and still catches invalid tracked-set/root behavior.
- Golden tests pass with default fast marking.
- The no-runtime-trace benchmark shows reduced `rt_tracked_set_lookup_existing` and `rt_gc_collect` self time.

### How To Test

```bash
make -C runtime test-all
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" make -C runtime clean test-all
./scripts/golden.sh --filter 'runtime/**'
./scripts/golden.sh --filter 'aoc/2025/11/part2/**'
NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_current --omit-runtime-trace
perf stat -d ./build/solver2_perf_current < aoc/2025/11/part2/input.txt
perf record -o /tmp/solver2_fast_mark.data ./build/solver2_perf_current < aoc/2025/11/part2/input.txt > /tmp/solver2_fast_mark.stdout
perf report --stdio --no-children --sort symbol -i /tmp/solver2_fast_mark.data
```

### Exit Criteria

- Default marking no longer calls `rt_gc_tracked_set_contains`.
- Validation mode still has tracked-set membership checking.
- `rt_tracked_set_lookup_existing` drops materially in flat profiles.
- No GC correctness regressions in runtime, integration, or golden tests.

### Checklist

- [x] Split mark-time object validation into fast and validation paths.
- [x] Keep validation path using the tracked set.
- [x] Remove tracked-set lookup from default `rt_mark_ref_slot`.
- [x] Add or update runtime tests for both modes.
- [x] Run golden runtime coverage.
- [x] Re-profile `solver2` no-trace and record deltas.

### PR 2 Benchmark Note

Latest local no-runtime-trace `solver2` run after PR 2:

- elapsed: `1.97s`
- user: `1.95s`
- IPC: `2.72`
- branch misses: `1.09%`
- L1D miss rate: `4.14%`
- samples: `7,861`
- lost samples: `0`
- `rt_tracked_set_lookup_existing`: `4.95%`, down from about `8.88%` in the pre-plan reference
- remaining top costs are still GC/allocation/map heavy: `rt_gc_collect`, `Map__find_existing_index`, `rt_gc_tracked_set_insert`, `_int_malloc`, `__libc_calloc`, and `rt_gc_track_allocation`

## PR 3: Make Tracked-Set Allocation/Sweep Maintenance Optional In Fast Mode

### Purpose

If mark-time validation no longer needs the tracked set in default mode, stop maintaining that hash set on every allocation and sweep in default mode. The linked object list is still enough for sweep; the tracked set becomes a validation/debug structure.

### What To Do

- In [runtime/src/gc.c](../runtime/src/gc.c), gate these operations behind validation mode:
  - `rt_gc_tracked_set_insert(obj)` in `rt_gc_track_allocation`
  - `rt_gc_tracked_set_remove(obj)` in `rt_sweep_unmarked`
  - any tracked-set reset behavior that is only needed when the set is enabled
- Keep the linked `g_tracked_objects` list and tracked-node pool exactly as-is. This PR is not intrusive metadata and not a freelist.
- Keep [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c) and its tests. It remains useful for validation mode and targeted data-structure tests.
- Extend stats so tests can verify whether the tracked set is active in the current build.
- Make sure validation mode still inserts/removes every object and still exercises tracked-set probe stats.

### Where

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/src/gc_tracked_set.c](../runtime/src/gc_tracked_set.c), only if reset/stats behavior needs minor adjustment
- [tests/runtime/test_tracked_set_gc_integration.c](../tests/runtime/test_tracked_set_gc_integration.c)
- [tests/runtime/test_gc_tracking_pool.c](../tests/runtime/test_gc_tracking_pool.c)
- [tests/runtime/test_tracked_set_probe_behavior.c](../tests/runtime/test_tracked_set_probe_behavior.c)
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Default mode:
  - GC correctness still passes.
  - tracked-set insert/remove should not appear in the flat benchmark profile except through explicitly tracked-set tests.
- Validation mode:
  - tracked-set integration tests still prove membership behavior.
  - probe stats still work.
- The no-runtime-trace benchmark shows reduced `rt_gc_tracked_set_insert`, `rt_gc_tracked_set_remove`, and `rt_tracked_set_rehash_live_entries`.

### How To Test

```bash
make -C runtime test-all
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" make -C runtime clean test-all
./scripts/golden.sh --filter 'runtime/**'
NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_current --omit-runtime-trace
perf stat -d ./build/solver2_perf_current < aoc/2025/11/part2/input.txt
perf record -o /tmp/solver2_no_tracked_set_fastpath.data ./build/solver2_perf_current < aoc/2025/11/part2/input.txt > /tmp/solver2_no_tracked_set_fastpath.stdout
perf report --stdio --no-children --sort symbol -i /tmp/solver2_no_tracked_set_fastpath.data
```

### Exit Criteria

- Default allocation no longer inserts into the tracked set.
- Default sweep no longer removes from the tracked set.
- Validation mode preserves current tracked-set behavior.
- Flat profile no longer has tracked-set maintenance as a first-order cost in the benchmark.

### Checklist

- [x] Gate tracked-set insert/remove behind validation mode.
- [x] Keep linked object-list tracking unchanged.
- [x] Keep tracked-set standalone tests intact.
- [x] Update stats/tests to distinguish active and inactive tracked-set mode.
- [x] Run default runtime and golden tests.
- [x] Run validation-mode runtime tests.
- [x] Re-profile and record tracked-set hotspot deltas.

### PR 3 Benchmark Note

Latest local no-runtime-trace `solver2` run after PR 3:

- elapsed: `1.60s`
- user: `1.56s`
- IPC: `2.95`
- branch misses: `0.68%`
- L1D miss rate: `4.16%`
- samples: `6,407`
- lost samples: `0`
- tracked-set maintenance symbols were no longer present in the flat profile
- `rt_gc_tracked_set_insert`, `rt_gc_tracked_set_remove`, `rt_tracked_set_lookup_existing`, and `rt_tracked_set_rehash_live_entries` were absent from the top flat report
- remaining top costs are `rt_gc_collect`, `Map__find_existing_index`, allocator internals, `find_all_paths_dag`, `Map__insert_or_assign`, and `rt_mark_ref_slot`

## PR 4: Add Small-Object Freelist Stats And Eligibility Helpers

### Purpose

Prepare the allocator change with observability and a narrow eligibility policy before recycling any objects. This keeps the first allocator PR behavior-preserving.

### What To Do

- Add a runtime-local size-class table for fixed-size GC objects.
- Suggested initial buckets by total object size:
  - 32 bytes
  - 40 bytes
  - 48 bytes
  - 64 bytes
  - 80 bytes
  - 96 bytes
  - 128 bytes
- Add helper functions in [runtime/src/runtime.c](../runtime/src/runtime.c) or a new runtime-local allocator module:
  - classify total object size
  - check whether a type is eligible
  - report bucket stats
- Eligibility rules:
  - fixed-size objects only
  - skip `RT_TYPE_FLAG_VARIABLE_SIZE`
  - skip sizes outside the bucket table
  - fallback to current `calloc` path
- Add stats in [runtime/include/gc.h](../runtime/include/gc.h) or a new allocator header:
  - allocation requests by bucket
  - freelist hits
  - freelist misses
  - returned objects
  - retained objects
  - fallback allocations
- Do not reuse objects yet.

### Where

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/Makefile](../runtime/Makefile)
- new test: `tests/runtime/test_small_object_freelist.c`
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Bucket classification handles supported and unsupported sizes.
- Variable-size objects are not eligible.
- Stats reset correctly in `rt_gc_reset_state`.
- No behavior changes yet.

### How To Test

```bash
make -C runtime test-small-object-freelist
make -C runtime test-all
./scripts/golden.sh --filter 'runtime/**'
```

### Checklist

- [ ] Add size-class table.
- [ ] Add eligibility helper for fixed-size GC objects.
- [ ] Add freelist stats structure.
- [ ] Add stats reset path.
- [ ] Add focused runtime test for classification and stats.
- [ ] Keep allocation behavior unchanged.

## PR 5: Allocate Small Objects From Freelists

### Purpose

Route eligible fixed-size objects through a bounded freelist before falling back to `calloc`. This attacks `__libc_calloc`, `_int_malloc`, and allocator consolidation cost.

### What To Do

- Change `rt_try_alloc_zeroed` in [runtime/src/runtime.c](../runtime/src/runtime.c) to try a freelist pop for eligible total sizes.
- On freelist hit:
  - pop one block
  - zero the full object size
  - return it
- On freelist miss:
  - fall back to current `calloc`
- Keep retry-after-GC behavior:
  - if fallback allocation fails, collect and retry
  - after collection, try freelist again before final fallback if the code stays simple
- Keep freelist code local and easy to audit.

### Where

- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/src/gc.c](../runtime/src/gc.c), if ownership of freelist data lives there
- [runtime/include/gc.h](../runtime/include/gc.h)
- `tests/runtime/test_small_object_freelist.c`
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Eligible allocations can hit a freelist after objects are returned by a later PR or test-only seeding.
- Unsupported allocations still use fallback allocation.
- Objects returned from freelist are zeroed.
- Object header initialization in `rt_alloc_obj` remains correct.

### How To Test

```bash
make -C runtime test-small-object-freelist
make -C runtime test-all
./scripts/golden.sh --filter 'runtime/**'
```

### Checklist

- [ ] Implement freelist pop path.
- [ ] Preserve `calloc` fallback path.
- [ ] Preserve collect-and-retry behavior.
- [ ] Verify reused blocks are zeroed before header initialization.
- [ ] Add tests for hit, miss, fallback, and zeroing behavior.
- [ ] Run runtime and golden tests.

## PR 6: Return Swept Small Objects To Bounded Freelists

### Purpose

Complete the recycling loop by returning eligible dead objects to freelists during sweep instead of immediately calling `free(obj)`.

### What To Do

- In [runtime/src/gc.c](../runtime/src/gc.c), update `rt_sweep_unmarked`:
  - if object is eligible and bucket is below retention cap, return it to the freelist
  - otherwise call `free(obj)` as today
- Add a per-bucket retention cap.
- Keep caps conservative at first. Suggested initial policy:
  - cap by object count per bucket, for example 4096 objects
  - expose stats so benchmark runs can tune later
- Make `rt_gc_reset_state` release all freelist-retained memory.
- Do not return variable-sized arrays or unsupported object sizes.
- Ensure validation mode and default fast mode both share the same freelist behavior.

### Where

- [runtime/src/gc.c](../runtime/src/gc.c)
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/gc.h](../runtime/include/gc.h)
- [runtime/Makefile](../runtime/Makefile)
- `tests/runtime/test_small_object_freelist.c`
- [tests/runtime/test_gc_stress.c](../tests/runtime/test_gc_stress.c)
- [docs/GC_ALLOCATION_FAST_PATH_PLAN.md](GC_ALLOCATION_FAST_PATH_PLAN.md)

### What To Test

- Repeated allocate/collect cycles reuse objects from freelists.
- Unsupported sizes still free normally.
- Retention cap is honored.
- `rt_gc_reset_state` releases retained memory and resets stats.
- Large golden workloads continue to pass under GC pressure.
- Benchmark shows reduced libc allocation/free self time.

### How To Test

```bash
make -C runtime test-small-object-freelist
make -C runtime test
make -C runtime test-all
./scripts/golden.sh --filter 'runtime/**'
./scripts/golden.sh --filter 'aoc/2025/11/part2/**'
NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_current --omit-runtime-trace
perf stat -d ./build/solver2_perf_current < aoc/2025/11/part2/input.txt
perf record -o /tmp/solver2_small_freelist.data ./build/solver2_perf_current < aoc/2025/11/part2/input.txt > /tmp/solver2_small_freelist.stdout
perf report --stdio --no-children --sort symbol -i /tmp/solver2_small_freelist.data
```

### Exit Criteria

- Eligible small fixed-size objects are recycled from freelists.
- Retained memory is bounded.
- Runtime reset releases freelist memory.
- `_int_malloc`, `__libc_calloc`, `_int_free`, and `malloc_consolidate` drop materially in flat profiles.
- GC correctness remains unchanged.

### Checklist

- [ ] Implement freelist return path in sweep.
- [ ] Add per-bucket retention caps.
- [ ] Release retained freelist memory in reset.
- [ ] Add tests for reuse across collections.
- [ ] Add tests for cap behavior.
- [ ] Add tests for unsupported-size fallback.
- [ ] Run runtime suite.
- [ ] Run golden runtime/AoC coverage.
- [ ] Re-profile and record allocator hotspot deltas.

## Validation Matrix

Run this matrix after PRs 2, 3, and 6.

### Default Fast Mode

```bash
make -C runtime test-all
./scripts/golden.sh
NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_current --omit-runtime-trace
perf stat -d ./build/solver2_perf_current < aoc/2025/11/part2/input.txt
perf record -o /tmp/solver2_default_fast.data ./build/solver2_perf_current < aoc/2025/11/part2/input.txt > /tmp/solver2_default_fast.stdout
perf report --stdio --no-children --sort symbol -i /tmp/solver2_default_fast.data
```

### Validation Mode

```bash
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" make -C runtime clean test-all
NIF_CC_ARGS="-DNIF_GC_VALIDATE_TRACKED_SET=1" NIF_PROFILE_BUILD=1 ./scripts/build.sh aoc/2025/11/part2/solver2.nif build/solver2_perf_validate --omit-runtime-trace
perf stat -d ./build/solver2_perf_validate < aoc/2025/11/part2/input.txt
```

## Benchmark Tracking Checklist

Use the no-runtime-trace `solver2` benchmark as the primary tracking workload.

Current pre-plan reference from the latest local run:

- elapsed: about `2.07s`
- user: about `2.01s`
- IPC: about `2.71`
- branch misses: about `1.11%`
- L1D miss rate: about `4.17%`
- top flat costs include `rt_gc_collect`, `rt_tracked_set_lookup_existing`, `Map__find_existing_index`, `rt_gc_tracked_set_insert`, `_int_malloc`, `Map__insert_or_assign`, and `__libc_calloc`

Record after each behavior-changing PR:

- [ ] elapsed time
- [ ] user time
- [ ] IPC
- [ ] branch miss rate
- [ ] L1D miss rate
- [ ] total samples and lost samples
- [ ] `rt_gc_collect`
- [ ] `rt_tracked_set_lookup_existing`
- [ ] `rt_gc_tracked_set_insert`
- [ ] `rt_gc_tracked_set_remove`
- [ ] `rt_tracked_set_rehash_live_entries`
- [ ] `rt_gc_track_allocation`
- [ ] `rt_alloc_obj`
- [ ] `__libc_calloc`
- [ ] `_int_malloc`
- [ ] `_int_free`
- [ ] `malloc_consolidate`

## Expected Outcome

After PRs 1-3, tracked-set costs should mostly disappear from the default benchmark profile, while validation mode preserves the old safety behavior.

After PRs 4-6, libc allocator churn should drop for small fixed-size objects. At that point the profile should shift toward real library semantics such as `Map` lookup, `Str` operations, and the unavoidable parts of GC mark/sweep. That is the right moment to revisit typed containers, register allocation, or a generational collector.
