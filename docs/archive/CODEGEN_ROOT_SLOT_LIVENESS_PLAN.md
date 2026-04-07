# Codegen Root-Slot Liveness Plan

This document defines a concrete implementation plan for overhauling root-slot synchronization in codegen.

The goal is to generate faster code by reducing unnecessary root-slot updates and other call-site scaffolding around runtime calls, while preserving the current GC and shadow-stack correctness model.

This is a backend execution-speed plan. It is not primarily a compiler-throughput plan.

## Why This Plan Exists

The current backend is conservative in a way that is safe but expensive:

- reference-typed locals are mirrored into shadow-stack root slots before many calls
- the mirroring is currently broad rather than precise
- runtime calls that do not allocate or trigger GC are still treated too much like full GC boundaries
- root-slot synchronization is emitted via helper calls even though the shadow-stack frame already points at stack-resident slot storage

This means the generated machine code pays repeated overhead from:

- redundant root-slot writes
- redundant helper calls to `rt_root_slot_store`
- redundant temp-root setup for calls that cannot collect
- repeated scaffolding around array operations, casts, type tests, and interface lookup

The current semantic optimization pipeline is no longer the main limiting factor for runtime speed. A significant part of the remaining overhead is introduced later, in executable lowering and codegen.

## Baseline Behavior Today

The current design spans these main pieces:

- [compiler/codegen/layout.py](compiler/codegen/layout.py)
  - allocates named value slots, named root slots, and temporary root slots
- [compiler/codegen/model.py](compiler/codegen/model.py)
  - stores `FunctionLayout`, including root-slot metadata
- [compiler/codegen/emitter_fn.py](compiler/codegen/emitter_fn.py)
  - sets up the root frame in function and constructor prologues
- [compiler/codegen/generator.py](compiler/codegen/generator.py)
  - emits root-slot synchronization and temporary root-slot updates
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
  - emits runtime calls, ordinary calls, interface dispatch, casts, and type tests
- [runtime/src/runtime.c](runtime/src/runtime.c)
  - implements `rt_root_frame_init`, `rt_root_slot_store`, `rt_push_roots`, and `rt_pop_roots`
- [runtime/src/gc.c](runtime/src/gc.c)
  - walks `frame->slots[i]` from the shadow stack during marking

Two current facts are important:

1. The GC only needs the shadow-stack slots to contain the correct live references at actual GC points.
2. `rt_root_slot_store` is currently only a checked assignment into `frame->slots[slot_index]`.

That means much of the current codegen overhead is not semantic work. It is synchronization policy and synchronization mechanism.

## Core Design Goal

Make root synchronization precise along three axes:

1. only synchronize named roots at calls that may trigger GC
2. only synchronize named roots that are live across that call
3. only synchronize named roots whose root slots are stale relative to the current local value

Separately, replace helper-call-based root-slot writes with direct stores into the already-allocated root-slot stack memory.

## Non-Goals

- do not redesign the GC
- do not replace the shadow-stack ABI
- do not attempt SSA or a new backend IR in this change set
- do not use this overhaul to sneak in unrelated codegen refactors
- do not weaken correctness for constructor allocation, runtime array allocation, or ordinary user-defined calls

## Main Architectural Decisions

## 1. Distinguish GC-capable calls from ordinary runtime calls

The backend currently has partial runtime-call metadata in [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py), mainly `RUNTIME_REF_ARG_INDICES`.

That is not enough. The backend also needs to know whether a call may trigger GC.

This distinction is central because many runtime helpers are non-allocating and non-collecting, including:

- `rt_array_len`
- `rt_array_get_*`
- `rt_array_set_*`
- `rt_array_set_slice_*`
- `rt_lookup_interface_method`
- `rt_checked_cast`
- `rt_checked_cast_interface`
- `rt_checked_cast_array_kind`
- `rt_is_instance_of_type`
- `rt_is_instance_of_interface`
- `rt_cast_*`

Likely GC-capable helpers include:

- `rt_alloc_obj`
- `rt_array_new_*`
- `rt_array_from_bytes_u8`
- `rt_array_slice_*`

Ordinary user-defined calls must remain conservative initially and be treated as GC-capable.

### Purpose

Avoid root synchronization and temp-root work at calls that cannot trigger collection.

### Expected Outcome

- less call-site scaffolding around common runtime helpers
- faster array-heavy and type-check-heavy generated code
- a clear backend policy surface for future optimizations

## 2. Distinguish named roots from temp roots

Named roots and temp roots solve different problems:

- named roots protect long-lived locals across GC points
- temp roots protect ephemeral expression results not yet stored in named local slots

The current code already models them separately in the layout, but the emission policy still treats them too uniformly.

### Purpose

Target precise liveness at named roots first while keeping temporary rooting conservative where it is still needed.

### Expected Outcome

- simpler reasoning about correctness
- smaller first implementation slice
- better performance without destabilizing expression-evaluation safety

## 3. Track dirty named roots during emission

Static liveness alone is not sufficient. A named root can be live across a call but already synchronized.

The backend therefore needs a small mutable state in emission context that tracks which named reference locals have changed since their corresponding root slots were last refreshed.

### Purpose

Prevent repeated resynchronization of unchanged locals before every GC-capable call.

### Expected Outcome

- fewer root writes in call-heavy code
- especially good payoff inside loops and object-heavy methods

## 4. Emit direct stores for root-slot synchronization

Because `RtRootFrame.slots` points at stack-allocated slot storage, generated code can write directly to root-slot memory instead of calling `rt_root_slot_store`.

For generated code, root synchronization should become a plain store into `layout.root_slot_offsets[...]` or `layout.temp_root_slot_offsets[...]` whenever possible.

### Purpose

Remove helper-call overhead from synchronization itself.

### Expected Outcome

- fewer runtime helper calls
- smaller and faster assembly
- unchanged runtime semantics

## High-Level Plan

This overhaul should be implemented in ordered slices.

## Slice 1: Add call-effect metadata

Status: implemented

Payoff: high

Risk: low

### Purpose

Give the backend enough information to distinguish GC-capable calls from non-GC runtime calls.

### Where To Change

- [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py)
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- [compiler/codegen/generator.py](compiler/codegen/generator.py)

### Concrete Changes

- [x] replace or supplement `RUNTIME_REF_ARG_INDICES` with a richer metadata table such as:
  - runtime target name
  - reference argument indices
  - `may_gc`
  - optional `needs_runtime_hooks` if hooks later become separately tunable
- [x] add helper accessors so emission code asks for runtime call properties instead of hard-coding policy by call name
- [x] update the shared call-emission path to branch on `may_gc`

### Expected Outcome

- non-allocating runtime helpers stop paying full GC-boundary cost
- policy becomes centralized rather than duplicated

### Tests

- [x] add unit tests for runtime-call metadata classification
- [x] update codegen tests to distinguish:
  - GC-capable runtime calls
  - non-GC runtime calls
  - ordinary user-defined calls

## Slice 2: Stop using helper calls for named-root synchronization

Status: implemented

Payoff: very high

Risk: low to medium

### Purpose

Replace helper-call-based named-root updates with direct stores into stack-resident root-slot memory.

### Where To Change

- [compiler/codegen/generator.py](compiler/codegen/generator.py)
- [compiler/codegen/model.py](compiler/codegen/model.py)
- [compiler/codegen/layout.py](compiler/codegen/layout.py)

### Concrete Changes

- [x] replace `emit_root_slot_updates(layout)` with an API that emits direct stores to root-slot offsets
- [x] make the API accept the specific set of named locals to synchronize instead of always iterating all named root slots
- [x] preserve the existing root-frame setup and root-slot layout; only change the synchronization mechanism

### Expected Outcome

- no `rt_root_slot_store` helper calls for ordinary named-root refreshes
- immediate reduction in instruction count even before full liveness is added

### Tests

- [x] update [tests/compiler/codegen/test_emit_asm_runtime_roots.py](tests/compiler/codegen/test_emit_asm_runtime_roots.py)
  - stop asserting helper-call presence for named-root refreshes
  - instead assert the correct stack-slot stores and correct root-frame setup
- [x] keep tests that verify constructor/root-frame ABI unchanged unless emitted structure genuinely improves

## Slice 3: Add lowered-IR named-root liveness analysis

Status: implemented

Payoff: very high

Risk: medium

### Purpose

Compute which named reference locals are actually live across each GC-capable call site.

### Why Lowered IR

The analysis should run after executable lowering because:

- executable lowering introduces helper locals for `for-in`
- codegen operates on lowered control-flow and call structure, not the earlier semantic graph
- the backend needs liveness relative to actual emitted evaluation order

### Where To Change

- add a new module, for example `compiler/codegen/root_liveness.py`
- possibly reuse helpers from [compiler/semantic/optimizations/helpers/local_usage.py](compiler/semantic/optimizations/helpers/local_usage.py)
- integrate into [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py) and [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)

### Concrete Changes

- [x] implement backward liveness for lowered statements
- [x] implement expression-local liveness that mirrors actual codegen evaluation order
- [x] produce a call-site plan describing which named reference locals are live across each call
- [x] initially scope this to named locals only; keep temp-root logic separate

### Expected Outcome

- synchronization shrinks from “all named roots” to “live named roots”
- fewer root-slot writes in loops, branches, and call chains

### Tests

- [x] add analysis-focused unit tests for:
  - straight-line calls
  - nested calls
  - branches
  - loops
  - lowered `for-in`
- [x] add codegen regressions showing that dead reference locals are no longer synchronized before GC-capable calls

## Slice 4: Add dirty-root tracking in emission context

Status: implemented

Payoff: very high

Risk: medium

### Purpose

Synchronize only named roots that are both live across the call and stale.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
- [compiler/codegen/emitter_fn.py](compiler/codegen/emitter_fn.py)

### Concrete Changes

- [x] extend `EmitContext` with dirty-root state
- [x] mark reference locals dirty when their value slot changes:
  - param spills in function prologue
  - ref-typed `SemanticVarDecl` initialization
  - ref-typed `SemanticAssign` to locals
- [x] before a GC-capable call, compute:
  - `locals_to_sync = live_named_roots_at_call ∩ dirty_named_roots`
- [x] emit synchronization only for `locals_to_sync`
- [x] mark synchronized locals clean after the refresh

### Expected Outcome

- unchanged locals stop being rewritten into root slots before every call
- repeated method and runtime calls inside loops become cheaper

### Tests

- [x] add codegen tests where:
  - a reference local is written once and used across several calls
  - only one of several reference locals changes before the next GC-capable call
  - loops repeatedly call a GC-capable helper without mutating every reference local

## Slice 5: Gate temp-rooting on call effects

Status: implemented

Payoff: high

Risk: medium

### Purpose

Avoid temporary root-slot setup for runtime calls that cannot collect.

### Where To Change

- [compiler/codegen/generator.py](compiler/codegen/generator.py)
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- [compiler/codegen/layout.py](compiler/codegen/layout.py)

### Concrete Changes

- [x] for non-GC runtime calls, skip temp-root setup for ephemeral values whose lifetime only needs to span that call
- [x] keep temp-rooting for:
  - allocation paths
  - array slice constructors
  - ordinary user-defined calls
  - indirect calls until proven otherwise
- [x] revisit the sizing logic in `layout.py` once temp-root demand becomes more precise

### Expected Outcome

- fewer temp-root stores and clears
- less stack traffic in array operations, interface lookup, and checked-cast code paths

### Tests

- [x] extend [tests/compiler/codegen/test_emit_asm_calls.py](tests/compiler/codegen/test_emit_asm_calls.py)
- [x] extend [tests/compiler/codegen/test_emit_asm_arrays.py](tests/compiler/codegen/test_emit_asm_arrays.py)
- [x] add targeted tests proving that non-GC runtime helpers do not receive unnecessary temp-root scaffolding

## Slice 6: Normalize interface-dispatch call structure

Status: implemented

Payoff: medium to high

Risk: medium

### Purpose

Apply the new call-effect rules to interface dispatch, which currently performs a runtime lookup and then a real indirect call.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)

### Concrete Changes

- [x] classify `rt_lookup_interface_method` as non-GC
- [x] stop treating the lookup call like a full GC boundary
- [x] keep conservative rooting only for the actual indirect call that follows

### Expected Outcome

- interface dispatch becomes substantially cheaper without changing semantics

### Tests

- [x] update [tests/compiler/codegen/test_emit_asm_calls.py](tests/compiler/codegen/test_emit_asm_calls.py)
  - interface lookup should still occur
  - root synchronization around the lookup itself should be reduced

## Slice 7: Optional dead-root clearing follow-up

Status: implemented

Payoff: medium

Risk: medium

### Purpose

Reduce GC retention by clearing dead named roots or dead temp roots when worthwhile.

### Important Note

This is not required for the main performance win. It adds writes, so it should be considered only after the faster-sync plan is stable and measured.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
- [compiler/codegen/generator.py](compiler/codegen/generator.py)

### Expected Outcome

- lower GC retention pressure in long-lived functions
- possible memory-footprint improvement
- uncertain runtime-speed benefit

### Tests

- [x] add codegen regressions proving that dead named roots are cleared after their last live use
- [x] add regressions proving that stale named roots are cleared after dead local writes

## Detailed File-Level Change Map

## `compiler/codegen/abi/runtime.py`

### Purpose

Become the authoritative source for runtime-call backend policy.

### Changes

- introduce richer runtime-call metadata
- classify runtime helpers by `may_gc`
- keep reference-argument metadata co-located with call effects

### Expected Outcome

- all backend call policy derives from one table

## `compiler/codegen/generator.py`

### Purpose

Own the mechanics of direct root-slot synchronization and temp-root updates.

### Changes

- replace helper-call-based root-slot updates with direct stores
- add APIs that synchronize a selected set of named roots
- retain frame setup, push/pop, and temp-slot clearing helpers where still needed

### Expected Outcome

- less runtime helper overhead
- smaller assembly at many call sites

## `compiler/codegen/emitter_expr.py`

### Purpose

Use call-effect metadata plus root-liveness plans while preserving expression evaluation order.

### Changes

- integrate runtime call classification
- consult named-root liveness at call sites
- apply dirty-root filtering before GC-capable calls
- reduce or remove sync around non-GC runtime helpers
- split interface lookup from indirect call in policy terms

### Expected Outcome

- most visible code-size and runtime-speed improvement in the backend

## `compiler/codegen/emitter_stmt.py`

### Purpose

Mark named roots dirty when statements update reference-typed locals.

### Changes

- update local declaration and assignment paths to maintain dirty-root state
- preserve existing statement semantics

### Expected Outcome

- backend state accurately reflects when root slots are stale

## `compiler/codegen/emitter_fn.py`

### Purpose

Initialize dirty-root state consistently at function entry.

### Changes

- decide whether ref-typed params begin dirty or are synchronized as part of prologue policy
- keep root-frame setup unchanged except for synchronization strategy

### Expected Outcome

- correct starting state for later precise synchronization

## `compiler/codegen/layout.py`

### Purpose

Continue to size named and temp root infrastructure, but evolve to support more precise temp-root demand.

### Changes

- keep current root-slot layout structure initially
- later narrow temp-root demand once call-effect gating is in place

### Expected Outcome

- compatibility with current stack frame model during incremental rollout

## `runtime/src/runtime.c`

### Purpose

Remain the stable shadow-stack ABI boundary.

### Changes

- none required for the main plan if generated code writes root slots directly
- optional future comment updates documenting that compiler-generated direct slot stores are expected

### Expected Outcome

- no runtime ABI churn required for the main speed win

## `runtime/src/gc.c`

### Purpose

Remain unchanged in behavior: GC scans `frame->slots`.

### Changes

- no algorithmic change required

### Expected Outcome

- backend optimization lands without changing collector logic

## What To Test

Tests should move away from asserting the old helper mechanism and toward asserting the correct invariants and reduced scaffolding.

## Correctness Tests

- shadow-stack frame setup still occurs when reference roots exist
- primitive-only functions still omit root-frame setup
- GC-capable runtime calls still preserve all live references
- constructors still root allocated objects correctly
- temp-rooting still protects ephemeral references across GC-capable calls
- ordinary user-defined calls remain conservative

## Precision Tests

- non-GC runtime calls do not trigger named-root synchronization
- non-GC runtime calls do not trigger temp-root setup when not otherwise needed
- dead named reference locals are not synchronized before a GC-capable call
- live but already-clean named reference locals are not redundantly synchronized
- only the modified live reference local is resynchronized before the next GC-capable call

## Regression Targets

- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/compiler/codegen/test_emit_asm_calls.py](tests/compiler/codegen/test_emit_asm_calls.py)
- [tests/compiler/codegen/test_emit_asm_arrays.py](tests/compiler/codegen/test_emit_asm_arrays.py)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](tests/compiler/codegen/test_emit_asm_casts_metadata.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](tests/compiler/codegen/test_emit_asm_runtime_roots.py)

## Suggested New Test Cases

1. one live ref local, one dead ref local, one GC-capable runtime call
2. repeated non-GC runtime calls after a single ref-local assignment
3. loop with a stable ref local and repeated array length calls
4. interface method lookup followed by indirect call, asserting reduced lookup-side scaffolding
5. nested temporary reference expressions passed to:
   - a non-GC runtime helper
   - a GC-capable runtime helper
6. constructor or array-slice allocation proving temp roots still protect ephemeral values

## Measurement Strategy

This overhaul is intended to improve runtime speed. It should therefore be measured with backend-output metrics in addition to correctness tests.

Suggested metrics:

- count of emitted `rt_root_slot_store` helper calls before and after
- total emitted instruction count for representative array, cast, and interface-dispatch kernels
- microbenchmarks for:
  - array iteration
  - repeated casts and type tests
  - interface method dispatch
  - constructor-heavy code

## Risks And Mitigations

## Risk 1: Missing a live root at a true GC boundary

Mitigation:

- keep ordinary user-defined and indirect calls conservative
- land call-effect metadata before liveness precision
- add focused GC-safety regressions around allocation and array slicing

## Risk 2: Expression-order mismatch between analysis and emission

Mitigation:

- derive expression-local liveness rules from actual emission order in [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- add tests for nested calls and reversed argument evaluation

## Risk 3: Over-updating tests to the old mechanism

Mitigation:

- shift tests toward invariants and relative reduction rather than exact old helper sequences

## Risk 4: Plan grows into a broad codegen rewrite

Mitigation:

- keep slices independent
- do not mix this work with devirtualization, array fast paths, or type-narrowing elimination in the same series

## Ordered Implementation Checklist

1. [x] Add runtime call-effect metadata in [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py)
2. [x] Update shared call emission to branch on `may_gc`
3. [x] Replace helper-based named-root synchronization with direct stores in [compiler/codegen/generator.py](compiler/codegen/generator.py)
4. [x] Update codegen tests to assert root-slot state and reduced scaffolding rather than helper-call presence
5. [x] Add a lowered-IR named-root liveness analysis module
6. [x] Integrate the analysis into call-site emission in [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
7. [x] Extend `EmitContext` with dirty-root tracking
8. [x] Mark ref locals dirty from prologue spills, var declarations, and local assignments
9. [x] Synchronize only `live ∩ dirty` named roots before GC-capable calls
10. [x] Gate temp-root setup and clearing on call effects
11. [x] Tighten interface lookup emission so the lookup helper is treated as non-GC
12. [x] Re-run the full codegen and runtime-root test suite
13. [x] Measure emitted scaffolding and representative runtime kernels
14. [x] Decide to land dead-root clearing as a follow-up slice (implemented ahead of item 13 at user request)

Measurement implementation:

- [x] add [scripts/measure_root_liveness.py](scripts/measure_root_liveness.py) for repeatable measurement runs
- [x] add representative kernels under [samples/measurements/root_liveness](samples/measurements/root_liveness)
- [x] report focused-function assembly lines, instruction counts, helper-call counts, sync/clear block counts, binary size, and runtime timings

Suggested command:

- `python3 scripts/measure_root_liveness.py`

## Definition Of Success

This overhaul succeeds if, after the main slices land:

- non-GC runtime helpers no longer pay full GC-boundary root synchronization cost
- named-root synchronization is limited to live and dirty reference locals
- helper-call-based root-slot refreshes are gone from ordinary generated code paths
- temp-rooting remains correct at true GC boundaries
- codegen tests remain green after being updated to assert the new invariants
- representative generated code is measurably smaller and faster in call-heavy and collection-heavy paths