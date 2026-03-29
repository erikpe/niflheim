# Collection Fast Paths Plan

This document defines a concrete implementation plan for adding collection fast paths, with initial focus on arrays.

The goal is to generate faster code for common collection operations by bypassing generic runtime-call paths where the compiler already knows enough to emit direct accesses safely.

This is a backend execution-speed plan. It is not primarily a compiler-throughput plan.

## Why This Plan Exists

The current compiler already recognizes arrays structurally during semantic lowering, but many array operations still pay generic runtime-call costs later in the pipeline.

Today that means generated machine code often pays repeated overhead from:

- runtime calls for operations whose data layout is already known statically
- repeated call setup and stack reshaping around array helpers
- repeated temporary-root handling for operations that could be plain loads
- repeated per-iteration runtime calls in array-backed `for-in` loops
- loss of optimization leverage after executable lowering introduces loop helper locals and explicit control-flow structure

The current semantic optimization pipeline is no longer the main limiting factor for runtime speed in these cases. A significant part of the remaining overhead is introduced later, in executable lowering and codegen.

## Baseline Behavior Today

The current design spans these main pieces:

- [compiler/semantic/lowering/collections.py](compiler/semantic/lowering/collections.py)
  - recognizes structural array operations and lowers them to semantic array nodes such as `ArrayLenExpr`, `IndexReadExpr`, and `SliceReadExpr`
- [compiler/semantic/lowering/statements.py](compiler/semantic/lowering/statements.py)
  - lowers `for-in` to `SemanticForIn` with resolved collection dispatch
- [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py)
  - introduces helper locals and `LoweredSemanticForIn`
- [compiler/semantic/ir.py](compiler/semantic/ir.py)
  - defines `ArrayLenExpr`, `IndexReadExpr`, `SliceReadExpr`, and `SemanticForIn`
- [compiler/semantic/lowered_ir.py](compiler/semantic/lowered_ir.py)
  - defines `LoweredSemanticForIn`
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
  - emits array length, indexing, slice reads, and call sequences
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
  - emits lowered `for-in` loops
- [compiler/codegen/runtime_calls.py](compiler/codegen/runtime_calls.py)
  - maps `RuntimeDispatch` to runtime helper names
- [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py)
  - classifies runtime call effects and reference argument metadata
- [runtime/src/array.c](runtime/src/array.c)
  - defines the concrete runtime layout and semantics for arrays
- [runtime/include/array.h](runtime/include/array.h)
  - exposes array helper APIs

Two current facts are important:

1. Arrays already have a concrete runtime object layout in `runtime/src/array.c`:
   - object header
   - `len`
   - `element_kind`
   - `element_size`
   - `data[]`
2. The compiler already distinguishes structural arrays from generic collection-protocol dispatch during semantic lowering.

That means part of the current overhead is not due to missing type information. It is due to when and where the backend chooses to use generic runtime helpers.

## Core Design Goal

Add explicit fast-path lowering and code generation for array operations along three axes:

1. use direct loads for array length instead of `rt_array_len`
2. use specialized lowered-loop code for array-backed `for-in` instead of generic `iter_get` runtime calls
3. use direct indexed loads for array reads when semantics can be preserved without the generic runtime helper path

Separately, keep slice construction and slice assignment on the runtime path initially, because they still allocate, copy, and may interact with reference payload semantics.

## Non-Goals

- do not redesign the runtime array ABI
- do not replace the collection protocol with array-only semantics
- do not weaken null-check, bounds-check, or type expectations that are currently user-visible
- do not fold slice allocation into this initial work
- do not mix this work with unrelated backend refactors
- do not force codegen to rediscover semantic facts that lowering already knows

## Main Architectural Decisions

## 1. Arrays need a dedicated fast-path track, not just more semantic optimization

Semantic optimization already sees array expressions such as `ArrayLenExpr` and `IndexReadExpr`, but that is not enough by itself. The important choice is whether executable lowering and codegen preserve array-specific intent all the way into backend emission.

### Purpose

Avoid spending engineering effort on semantic rewrites that cannot remove the backend scaffolding introduced later.

### Expected Outcome

- better leverage from lowering-time knowledge
- simpler backend policy
- fewer repeated runtime calls in hot array code

## 2. Preserve fast-path eligibility in lowered IR instead of re-deriving it in codegen

The compiler already knows whether a given collection operation is a structural array operation in [compiler/semantic/lowering/collections.py](compiler/semantic/lowering/collections.py). That fact should be preserved explicitly when lowering to executable-oriented IR.

### Purpose

Keep semantic decisions in lowering, and keep codegen focused on emission rather than backend-side semantic pattern matching.

### Expected Outcome

- clearer architecture
- easier testing
- less duplication between lowering and codegen

## 3. Separate cheap, non-allocating array accesses from slice and allocation paths

Not all collection operations are equally good fast-path candidates.

The first fast-path group should be:

- array length
- array iteration length snapshot
- array iteration element fetch
- standalone array indexed read

The initial non-fast-path group should remain:

- array slice get
- array slice set
- array construction
- any generic collection protocol dispatch for non-array receivers

### Purpose

Target the operations with the best payoff-to-risk ratio first.

### Expected Outcome

- immediate wins for loops and indexing-heavy code
- lower implementation risk
- no premature entanglement with allocation and copy semantics

## 4. Centralize array layout constants in compiler-side ABI helpers

The backend should not scatter hard-coded array offsets through emitters.

The array object layout currently lives in [runtime/src/array.c](runtime/src/array.c) and depends on [runtime/include/runtime.h](runtime/include/runtime.h). The compiler should introduce one ABI-oriented helper module for array layout constants and direct-load helpers.

### Purpose

Keep direct array access maintainable and keep the compiler-side ABI surface explicit.

### Expected Outcome

- no magic offsets spread across codegen
- easier future runtime-ABI evolution
- smaller risk of backend/runtime divergence

## 5. Preserve runtime-visible safety semantics explicitly

The generic array helpers currently provide null checks, object-kind checks, and bounds or range validation in [runtime/src/array.c](runtime/src/array.c).

Any fast path must deliberately preserve whichever of those checks remain part of the language/runtime contract.

For the initial rollout, the fast path should preserve:

- null handling
- array-object expectation for structural array operations
- bounds checks for indexed reads and iteration element fetches

The implementation may preserve those semantics through direct inline checks rather than through helper calls.

### Purpose

Avoid accidental semantic weakening while removing generic helper overhead.

### Expected Outcome

- performance improvement without behavior drift
- safer staged rollout

## 6. Any `ref[]` fast write must go through one compiler-side helper

Direct primitive stores can safely inline payload writes under the current runtime contract. `ref[]` fast writes are different because they are the most likely future mutation point for GC write barriers, remembered sets, or other store-side invariants if the collector evolves.

If `ref[]` indexed writes ever join the fast path, the backend must not emit raw reference-slot stores from multiple places. One compiler-side helper in the array ABI/emission layer must be the only legal fast-path mutation site.

### Purpose

Keep GC-sensitive reference mutation centralized so future collector upgrades do not require a broad backend audit.

### Expected Outcome

- `ref[]` fast writes remain reasonably safe under the current stop-the-world non-moving collector
- a future GC change has one clear barrier insertion point instead of many scattered raw stores
- the hazard is documented explicitly in compiler/runtime notes rather than being implicit backend knowledge

## High-Level Plan

This work should be implemented in ordered slices.

## Slice 1: Add compiler-side array ABI helpers

Status: implemented

Payoff: medium

Risk: low

### Purpose

Create a single compiler-side place for array layout constants and direct-access helper routines used by codegen.

### Where To Change

- add a new module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)

### Concrete Changes

- [x] define constants for:
  - offset of array `len`
  - offset of array `element_kind`
  - offset of array `element_size`
  - offset of array `data`
- [x] add small helper emitters or address helpers for:
  - loading array length
  - computing array element address
  - reading element-kind when needed
- [x] document the correspondence to the runtime layout in [runtime/src/array.c](runtime/src/array.c)

### Expected Outcome

- one authoritative backend surface for array direct-access ABI assumptions
- no magic offsets embedded in expression or statement emitters

### Tests

- [x] add unit tests for ABI constants if exposed as helpers
- [x] add codegen-facing tests that validate operand and address formatting against the runtime layout assumptions

## Slice 2: Add explicit lowered-IR fast-path representation for arrays

Status: implemented

Payoff: high

Risk: medium

### Purpose

Preserve array fast-path eligibility across executable lowering so codegen does not need to reconstruct it from scratch.

### Where To Change

- [compiler/semantic/lowered_ir.py](compiler/semantic/lowered_ir.py)
- [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py)
- possibly [compiler/semantic/ir.py](compiler/semantic/ir.py) if lightweight strategy markers are needed earlier

### Concrete Changes

- [x] extend lowered IR with an explicit fast-path representation via a `strategy` field on `LoweredSemanticForIn`
- [x] preserve whether the iteration receiver is:
  - structural array with direct fast path
  - generic runtime-dispatch array path
  - non-array protocol dispatch path
- for indexed reads, preserve whether the target is eligible for direct array read codegen instead of only storing a generic `RuntimeDispatch`

### Expected Outcome

- codegen can branch on explicit lowering intent rather than on fragile backend-side pattern matching
- future collection fast paths have a stable insertion point

### Tests

- [x] add lowering tests proving array-backed `for-in` is marked for the specialized lowered form
- [x] add lowering tests proving generic non-array iteration remains on protocol dispatch

## Slice 3: Add direct array length emission

Status: implemented

Payoff: high

Risk: low

### Purpose

Replace `rt_array_len` runtime calls with direct field loads for structural array length operations.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- new helper module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- possibly [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py) only for consistency and policy documentation

### Concrete Changes

- [x] teach `ArrayLenExpr` emission to:
  - evaluate the array operand once
  - preserve null semantics through an inline check or dedicated helper emission
  - load `len` directly from the array object
- [x] skip:
  - runtime call hooks for `rt_array_len`
  - runtime call argument setup
  - generic runtime dispatch for structural arrays

### Expected Outcome

- no `rt_array_len` call in emitted array length code
- reduced instruction count and stack traffic
- immediate speedup for length-heavy and loop-heavy code

### Tests

- [x] update or add codegen tests asserting that structural array length emits no `rt_array_len` call
- [x] add runtime-facing tests proving null behavior remains correct

## Slice 4: Add specialized array `for-in` emission

Status: implemented

Payoff: very high

Risk: medium

### Purpose

Replace the generic `iter_get` runtime call loop with direct array iteration when the lowered loop is over a structural array.

### Where To Change

- [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py)
- [compiler/semantic/lowered_ir.py](compiler/semantic/lowered_ir.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
- new helper module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)

### Concrete Changes

- [x] keep the existing helper locals for collection, length, and index, but specialize how they are populated and consumed for array-backed loops
- [x] emit loop setup as:
  - evaluate collection once
  - store collection local once
  - null-check once
  - load array length once directly
  - initialize index local
- [x] emit loop body setup as:
  - compare index against cached length
  - compute element address directly from `data + index * element_size`
  - load element into the element local
  - continue with normal lowered loop body
- [x] preserve the generic protocol-dispatch path for non-array receivers

### Expected Outcome

- no per-iteration `rt_array_get_*` call for array-backed `for-in`
- no generic `iter_len` runtime call for array-backed `for-in`
- major speedup in array iteration kernels

### Tests

- [x] add codegen tests proving array-backed `for-in` emits no `rt_array_len` or `rt_array_get_*` call
- [x] add tests for primitive and reference arrays separately
- [x] add runtime behavior tests for loop correctness, including null and bounds-relevant cases

## Slice 5: Add direct array indexed-read emission

Status: implemented

Payoff: high

Risk: medium

### Purpose

Replace `rt_array_get_*` runtime calls with direct indexed loads when the compiler already knows the receiver is a structural array.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- new helper module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- optionally [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py) if a lowered strategy bit is needed

### Concrete Changes

- [x] for structural array `IndexReadExpr`:
  - evaluate receiver once
  - evaluate index once
  - preserve null semantics
  - emit inline bounds checks
  - compute direct element address
  - load the element according to its runtime representation
- [x] keep generic runtime-dispatch reads for non-array collection receivers

### Expected Outcome

- no `rt_array_get_*` call for structural array reads
- reduced call overhead in indexing-heavy code
- better interaction with loop code and later backend cleanups

### Tests

- [x] add codegen tests asserting direct loads instead of `rt_array_get_*` calls
- [x] add negative tests covering out-of-bounds and null behavior
- [x] add tests for primitive arrays and reference arrays

## Slice 6: Leave slices on runtime helpers initially

Status: proposed

Payoff: medium

Risk: low

### Purpose

Keep the rollout focused on high-payoff, low-risk collection operations first.

### Why Not Slices Yet

Slice reads and slice writes in [runtime/src/array.c](runtime/src/array.c) still:

- allocate new arrays or copy ranges
- validate slice ranges
- perform memory copies
- interact with reference payload semantics for `ref[]`

They are not the same kind of cheap access as length and indexed reads.

### Expected Outcome

- narrower rollout surface
- lower correctness risk
- faster delivery of the highest-value wins

### Tests

- keep existing slice tests unchanged initially
- ensure array fast-path rollout does not change slice emission accidentally

## Slice 7: Direct primitive array indexed-write slice

Status: recommended next

Payoff: medium

Risk: medium

### Purpose

Capture the next remaining helper-dominated hot path after array length, iteration, and indexed reads.

### Why This Is A Follow-Up

While the current runtime implementation for `rt_array_set_*` is direct bounds-checked mutation, writes are a more future-sensitive area if GC write barriers or additional mutation invariants are introduced later.

The current recommendation is therefore:

- pursue direct indexed writes next for primitive arrays (`i64[]`, `u64[]`, `u8[]`, `bool[]`, `double[]`)
- keep `ref[]` indexed writes on the runtime path until write-barrier policy is clearer

### Where To Change

- [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
- [compiler/semantic/lowering/collections.py](compiler/semantic/lowering/collections.py) only for comments or minor normalization updates if needed
- [tests/compiler/codegen/test_emit_asm_arrays.py](tests/compiler/codegen/test_emit_asm_arrays.py)
- [tests/compiler/codegen/test_emitter_stmt.py](tests/compiler/codegen/test_emitter_stmt.py)
- [tests/compiler/integration/test_cli_runtime_smoke.py](tests/compiler/integration/test_cli_runtime_smoke.py)

### Concrete Changes

- [ ] add compiler-side direct store helpers for primitive array elements in [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- [ ] teach structural primitive `IndexLValue` emission in [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py) to:
  - evaluate receiver once
  - evaluate index once
  - evaluate value once
  - preserve null semantics through an inline check
  - preserve bounds behavior through an inline check
  - compute the direct element address from array data and element size
  - store the primitive payload directly without `rt_array_set_*`
- [ ] keep `ref[]` indexed writes on the runtime path for now
- [ ] rely on the existing lowering normalization in [compiler/semantic/lowering/collections.py](compiler/semantic/lowering/collections.py) so both `arr[i] = value` and structural method-form `arr.index_set(i, value)` flow through the same `IndexLValue` codegen path

### Expected Outcome

- no `rt_array_set_*` call for structural primitive array writes
- lower call overhead in mutation-heavy numeric kernels
- one shared write path for assignment sugar and structural method-form `index_set`

### Tests

- [ ] add codegen tests proving primitive `arr[i] = value` emits no `rt_array_set_*` call
- [ ] add codegen tests proving primitive `arr.index_set(i, value)` emits no `rt_array_set_*` call
- [ ] add negative tests covering null and out-of-bounds behavior for primitive direct writes
- [ ] add runtime-facing tests for representative primitive kinds (`i64`, `u8`, and one of `bool` or `double`)

## Slice 8: Guarded `ref[]` indexed-write follow-up

Status: deferred guarded follow-up

Payoff: potentially high

Risk: high

### Purpose

Allow `ref[]` indexed writes to benefit from the fast path without scattering future GC-sensitive mutation logic across the backend.

### Guard Rule

If this slice is taken, a dedicated ref-array store helper in [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py) must be the only legal fast-path mutation site.

No other emitter may open-code raw reference-slot stores for structural array writes.

### Where To Change

- [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- [compiler/codegen/emitter_stmt.py](compiler/codegen/emitter_stmt.py)
- [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py) for comments/policy notes
- [docs/COLLECTION_FAST_PATHS_PLAN.md](docs/COLLECTION_FAST_PATHS_PLAN.md)
- [docs/ABI_NOTES.md](docs/ABI_NOTES.md)
- [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md) or a future GC-design note if that becomes the better home for collector-evolution constraints

### Concrete Changes

- [ ] add a dedicated compiler-side ref-array fast-store helper that centralizes:
  - null checks
  - bounds checks
  - the final reference-slot store
- [ ] document in code comments that this helper is the future barrier insertion point if the GC later becomes generational, incremental, concurrent, or otherwise mutation-sensitive
- [ ] keep all structural `ref[]` fast writes routed through that helper and through no other direct store path
- [ ] update general documentation to note that compiler-emitted ref-array fast stores are a GC-upgrade-sensitive spot and must be revisited if collector invariants change

### Expected Outcome

- `ref[]` fast writes become possible without hiding a future GC hazard in scattered backend code
- the collector-upgrade-sensitive mutation site is visible in both code and documentation

### Tests

- [ ] add runtime tests covering store of a freshly allocated object into `ref[]` followed by GC
- [ ] add runtime tests covering overwrite of the last retained reference followed by GC
- [ ] add tests covering `null` stores and aliasing cases such as `arr[i] = arr[j]`
- [ ] add codegen regressions proving structural `ref[]` writes use the dedicated helper path if this slice lands

## Detailed File-Level Change Map

## `compiler/semantic/lowering/collections.py`

### Purpose

Remain the source of truth for recognizing structural array operations.

### Changes

- keep existing structural array recognition
- keep using `SemanticAssign(IndexLValue(...))` as the normalized lowering surface for structural array writes, including method-form `index_set`
- ensure the lowering surface exposes enough information for later fast-path selection

### Expected Outcome

- no semantic re-discovery needed in codegen

## `compiler/semantic/lowering/statements.py`

### Purpose

Continue lowering `for-in` into a semantic node that distinguishes iteration dispatch.

### Changes

- likely minimal; keep structural array versus generic collection dispatch visible to executable lowering

### Expected Outcome

- executable lowering can specialize array-backed loops cleanly

## `compiler/semantic/lowering/executable.py`

### Purpose

Become the main boundary where array-specific executable fast paths are selected.

### Changes

- extend lowered `for-in` lowering to preserve array fast-path eligibility explicitly
- optionally preserve direct-array strategy for indexed reads if needed by backend emission

### Expected Outcome

- backend emission can use explicit lowered strategy instead of heuristic reconstruction

## `compiler/semantic/lowered_ir.py`

### Purpose

Carry the explicit lowered representation for array fast paths.

### Changes

- add specialized lowered nodes or strategy fields for array-backed `for-in`
- ensure the representation distinguishes structural array fast path from generic collection dispatch

### Expected Outcome

- stable backend-facing contract for fast-path emission

## `compiler/codegen/abi/array.py`

### Purpose

Become the authoritative compiler-side source for direct array access ABI details.

### Changes

- define array layout offsets and helper routines for direct loads and element-address computation
- add direct primitive array store helpers for indexed-write fast paths
- if `ref[]` fast writes are later enabled, add the dedicated ref-array store helper here and nowhere else
- document correspondence to runtime array layout
- document that the ref-array store helper is the GC-upgrade-sensitive mutation boundary

### Expected Outcome

- backend/runtime agreement lives in one place

## `compiler/codegen/emitter_expr.py`

### Purpose

Emit direct array loads where lowered IR says a structural array fast path is valid.

### Changes

- emit direct array length loads for `ArrayLenExpr`
- emit direct indexed loads for structural array `IndexReadExpr`
- keep runtime helper calls for slices and non-array collection dispatch

### Expected Outcome

- major reduction in helper calls for array-heavy expression code

## `compiler/codegen/emitter_stmt.py`

### Purpose

Emit specialized array iteration loops and structural array write fast paths from lowered statement forms.

### Changes

- add direct array-backed `for-in` emission path
- add direct primitive array indexed-write emission for structural `IndexLValue`
- keep current generic lowered `for-in` path for non-array iteration
- keep `ref[]` indexed writes runtime-backed unless the guarded follow-up slice lands

### Expected Outcome

- no per-iteration `rt_array_get_*` call in array-backed loops
- no `rt_array_set_*` call for structural primitive array writes once Slice 7 lands

## `compiler/codegen/abi/runtime.py`

### Purpose

Remain the source of runtime-call effects and helper metadata.

### Changes

- minimal changes expected
- may gain comments or helpers clarifying which array helpers remain on the runtime path versus which are bypassed for structural arrays
- should explicitly document that `rt_array_set_ref` stays the semantic reference path until the guarded ref-array write slice lands

### Expected Outcome

- backend policy remains centralized for actual runtime calls

## `runtime/src/array.c`

### Purpose

Remain the runtime ABI reference for array object layout and semantics.

### Changes

- no algorithmic runtime change required for the initial fast-path plan
- optional future comment updates documenting the compiler’s direct-layout dependency
- if `ref[]` fast writes are ever added, runtime comments should continue to make `rt_array_set_ref` the fallback/reference semantics baseline

### Expected Outcome

- no runtime churn required for the first rollout

## Documentation Updates For Future GC Changes

### Purpose

Record explicitly that compiler-emitted `ref[]` fast writes are safe under the current collector model but become a potential unsafe spot if the GC later gains store-side invariants.

### Changes

- update [docs/ABI_NOTES.md](docs/ABI_NOTES.md) to note that any compiler-side ref-array fast-store helper is the future mutation-barrier insertion point
- update [docs/LANGUAGE_MVP_SPEC_V0.1.md](docs/LANGUAGE_MVP_SPEC_V0.1.md) or a future GC-design document to note that collector upgrades may require revisiting compiler-emitted `ref[]` mutation fast paths
- keep [docs/COLLECTION_FAST_PATHS_PLAN.md](docs/COLLECTION_FAST_PATHS_PLAN.md) aligned with the current chosen policy for `ref[]` writes

### Expected Outcome

- future GC upgrades have an explicit documentation breadcrumb for the mutation-sensitive spot
- the risk is discoverable without reverse-engineering the backend

## What To Test

Tests should focus on emitted structure, preserved behavior, and separation between array fast paths and generic collection/runtime paths.

## Correctness Tests

- array length still preserves null behavior
- array indexed reads still preserve bounds behavior
- primitive array indexed writes still preserve null and bounds behavior
- array-backed `for-in` still evaluates the collection once
- array-backed `for-in` still preserves element values and iteration order
- reference-array iteration keeps the collection safely alive across the loop
- non-array collection-protocol types still go through the generic dispatch path
- if `ref[]` fast writes land later, they still preserve reachability and overwrite semantics across GC

## Precision Tests

- structural array length emits no `rt_array_len` call
- structural array indexing emits no `rt_array_get_*` call
- structural primitive array writes emit no `rt_array_set_*` call
- structural array `for-in` emits no `rt_array_len` or `rt_array_get_*` call
- structural `ref[]` writes remain on the runtime path unless the guarded follow-up slice explicitly lands
- slice operations still use the runtime helpers unchanged
- non-array protocol iteration still uses dispatch rather than array-specific direct access

## Regression Targets

- [tests/compiler/semantic/test_lowering.py](tests/compiler/semantic/test_lowering.py)
- [tests/compiler/codegen/test_emit_asm_arrays.py](tests/compiler/codegen/test_emit_asm_arrays.py)
- [tests/compiler/codegen/test_emit_asm_calls.py](tests/compiler/codegen/test_emit_asm_calls.py)
- [tests/compiler/codegen/test_emit_asm_runtime_roots.py](tests/compiler/codegen/test_emit_asm_runtime_roots.py)
- [tests/runtime/test_array_runtime.c](tests/runtime/test_array_runtime.c)
- [tests/runtime/test_array_negative.c](tests/runtime/test_array_negative.c)

## Suggested New Test Cases

1. structural array `len()` emits direct field load and no `rt_array_len`
2. structural array `iter_get(0)` emits direct indexed load and no `rt_array_get_*`
3. array-backed `for-in` emits one cached length load and no per-iteration runtime helper calls
4. reference-array iteration preserves loop behavior and emitted rooting invariants
5. non-array collection-protocol implementation still lowers and emits through generic dispatch
6. slice reads and slice writes remain on the runtime path after fast-path rollout
7. negative index and out-of-bounds indexed reads still preserve failure behavior
8. primitive `arr[i] = value` emits direct stores and no `rt_array_set_*`
9. primitive `arr.index_set(i, value)` emits direct stores and no `rt_array_set_*`
10. structural `ref[]` writes remain runtime-backed until the guarded follow-up slice lands
11. if `ref[]` fast writes are later enabled, all such stores route through the dedicated helper rather than scattered raw stores

## Measurement Strategy

This work is intended to improve runtime speed. It should therefore be measured with backend-output metrics and representative loop kernels.

Suggested metrics:

- count of emitted `rt_array_len` calls before and after
- count of emitted `rt_array_get_*` calls before and after
- count of emitted `rt_array_set_*` calls before and after
- total emitted instruction count for array-length, array-indexing, and array-iteration kernels
- loop body instruction count for representative `for-in` examples
- microbenchmarks for:
  - repeated `len()` on arrays
  - array iteration over primitive arrays
  - array iteration over reference arrays
  - indexed reads in tight loops
  - indexed writes in tight loops for primitive arrays
  - pure `ref[]` indexed writes with no read-side work in the hot loop

Implemented command surface:

- [scripts/measure_collection_fast_paths.py](scripts/measure_collection_fast_paths.py)
  - builds each kernel twice: once with collection fast paths enabled and once with the existing runtime-helper path forced on for measurement
  - writes a JSON report to [build/measurements/collection_fast_paths/report.json](build/measurements/collection_fast_paths/report.json)

Current measurement snapshot from `python3 scripts/measure_collection_fast_paths.py`:

| kernel | fast focus instructions | fallback focus instructions | fast `rt_array_len` calls | fallback `rt_array_len` calls | fast `rt_array_get_*` calls | fallback `rt_array_get_*` calls | fast `rt_array_set_*` calls | fallback `rt_array_set_*` calls | fast median ms | fallback median ms | speedup |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `len_hot_loop` | 64 | 64 | 0 | 2 | 0 | 0 | 0 | 0 | 3.688 | 16.294 | 4.42x |
| `index_reads_i64` | 115 | 102 | 0 | 2 | 0 | 2 | 0 | 0 | 4.660 | 20.435 | 4.38x |
| `index_writes_i64` | 129 | 116 | 0 | 2 | 0 | 2 | 2 | 2 | 20.659 | 20.585 | 1.00x |
| `index_writes_ref` | 155 | 129 | 0 | 2 | 0 | 4 | 2 | 2 | 6.055 | 17.935 | 2.96x |
| `index_writes_ref_pure` | 110 | 110 | 0 | 2 | 0 | 0 | 2 | 2 | 5.953 | 5.946 | 1.00x |
| `for_in_i64` | 86 | 99 | 0 | 2 | 0 | 2 | 0 | 0 | 3.108 | 18.789 | 6.05x |
| `for_in_ref` | 89 | 102 | 0 | 2 | 0 | 2 | 0 | 0 | 1.499 | 5.889 | 3.93x |

These measurements confirm the expected tradeoff: helper-call removal delivers substantial runtime wins even when static focus-function instruction count stays flat or rises slightly in some kernels.

They also make the indexed-write decision clear:

- `index_writes_i64` is effectively unchanged between fast and fallback modes at 1.00x, even though both variants still retain `rt_array_set_*` in the hot path
- that means the already-landed read fast paths no longer move the needle much for primitive write-heavy kernels; the remaining cost is dominated by runtime indexed writes
- `index_writes_ref` still improves from read-side fast paths because it also performs structural reads
- the new pure write kernel `index_writes_ref_pure` is effectively flat at 1.00x and removes the read-side confounder entirely
- that shows the current residual hot cost for `ref[]` write-heavy kernels is the runtime write helper itself, not leftover read overhead

Conclusion: direct indexed writes are worth doing next, but the follow-up should be primitive-only at first.

## Risks And Mitigations

## Risk 1: Fast path drifts from runtime array ABI

Mitigation:

- centralize offsets in one compiler-side array ABI module
- document correspondence to [runtime/src/array.c](runtime/src/array.c)
- add targeted codegen tests that would fail if offsets drift

## Risk 2: Fast path weakens null or bounds behavior

Mitigation:

- preserve explicit inline checks for the initial rollout
- add negative tests covering null and out-of-bounds cases

## Risk 3: Backend pattern matching becomes semantic analysis by accident

Mitigation:

- preserve eligibility explicitly in lowered IR
- make executable lowering choose strategy rather than codegen inferring it heuristically

## Risk 4: Reference-array iteration interacts badly with GC/rooting

Mitigation:

- rely on the already-landed root-slot liveness and temp-root policy improvements
- keep collection local materialization explicit in lowered `for-in`
- add focused regressions around reference arrays and allocation-heavy loop bodies

## Risk 5: The plan grows into a broad collection-backend rewrite

Mitigation:

- start with length and `for-in`
- defer slices and writes
- keep non-array protocol dispatch unchanged initially

## Risk 6: `ref[]` fast writes become a hidden future GC hazard

Mitigation:

- make the dedicated compiler-side ref-array store helper the only legal fast-path mutation site
- keep `ref[]` writes out of the primitive write slice
- update [docs/ABI_NOTES.md](docs/ABI_NOTES.md) and this plan if `ref[]` fast writes land so the future collector-upgrade-sensitive spot is explicit

## Ordered Implementation Checklist

1. [x] Add compiler-side array ABI helpers in a new module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
2. [x] Document the compiler/runtime array-layout dependency in code comments near the new ABI helpers
3. [x] Extend lowered IR to carry explicit array fast-path strategy for `for-in`
4. [x] Update executable lowering to preserve array-backed iteration strategy explicitly
5. [x] Emit direct array length loads for `ArrayLenExpr`
6. [x] Add codegen tests proving structural arrays no longer call `rt_array_len`
7. [x] Emit specialized array-backed `for-in` loops without `rt_array_get_*` runtime calls
8. [x] Add codegen and runtime tests for primitive-array iteration
9. [x] Add codegen and runtime tests for reference-array iteration
10. [x] Emit direct structural-array indexed reads without `rt_array_get_*` runtime calls
11. [x] Add negative tests for null and out-of-bounds behavior under direct indexed-read fast paths
12. [ ] Confirm slice operations remain unchanged on the runtime path
13. [x] Measure instruction-count and runtime improvements on representative collection kernels
14. [x] Decide whether direct indexed writes are worth a follow-up plan
15. [ ] Implement primitive-only direct indexed-write fast paths for `i64[]`, `u64[]`, `u8[]`, `bool[]`, and `double[]`
16. [ ] Add codegen tests proving primitive structural writes emit no `rt_array_set_*` call for both `arr[i] = value` and structural method-form `arr.index_set(i, value)`
17. [ ] Add runtime tests proving primitive direct writes preserve null and bounds behavior
18. [x] Define the rule that a dedicated ref-array store helper is the only legal fast-path mutation site if `ref[]` writes later join the fast path
19. [x] Decide to keep `ref[]` indexed writes as a guarded follow-up rather than folding them into the primitive write slice
20. [ ] If `ref[]` fast writes are later enabled, route them through the dedicated helper and update general ABI/runtime documentation to mark it as a future GC-barrier insertion point

## Definition Of Success

This plan succeeds if, after the main slices land:

- structural array length no longer emits `rt_array_len`
- structural array-backed `for-in` no longer emits generic `iter_len` and per-iteration `iter_get` runtime calls
- structural array indexed reads no longer emit `rt_array_get_*`
- structural primitive array indexed writes no longer emit `rt_array_set_*`
- null and bounds behavior remains correct
- non-array collection protocol types continue to use the generic dispatch path unchanged
- slice operations remain correct and unchanged until a dedicated follow-up plan exists
- any future `ref[]` fast write path remains centralized behind one documented helper so GC upgrades have a single mutation-sensitive insertion point
- representative array-heavy kernels are measurably faster, with helper calls reduced or eliminated even if some call sites grow slightly in static instruction count