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

Status: proposed

Payoff: high

Risk: medium

### Purpose

Preserve array fast-path eligibility across executable lowering so codegen does not need to reconstruct it from scratch.

### Where To Change

- [compiler/semantic/lowered_ir.py](compiler/semantic/lowered_ir.py)
- [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py)
- possibly [compiler/semantic/ir.py](compiler/semantic/ir.py) if lightweight strategy markers are needed earlier

### Concrete Changes

- extend lowered IR with an explicit fast-path representation, for example:
  - `LoweredSemanticArrayForIn`, or
  - a `strategy` field on `LoweredSemanticForIn`
- preserve whether the iteration receiver is:
  - structural array with direct fast path
  - generic runtime-dispatch array path
  - non-array protocol dispatch path
- for indexed reads, preserve whether the target is eligible for direct array read codegen instead of only storing a generic `RuntimeDispatch`

### Expected Outcome

- codegen can branch on explicit lowering intent rather than on fragile backend-side pattern matching
- future collection fast paths have a stable insertion point

### Tests

- add lowering tests proving array-backed `for-in` is marked for the specialized lowered form
- add lowering tests proving generic non-array iteration remains on protocol dispatch

## Slice 3: Add direct array length emission

Status: proposed

Payoff: high

Risk: low

### Purpose

Replace `rt_array_len` runtime calls with direct field loads for structural array length operations.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- new helper module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- possibly [compiler/codegen/abi/runtime.py](compiler/codegen/abi/runtime.py) only for consistency and policy documentation

### Concrete Changes

- teach `ArrayLenExpr` emission to:
  - evaluate the array operand once
  - preserve null semantics through an inline check or dedicated helper emission
  - load `len` directly from the array object
- skip:
  - runtime call hooks for `rt_array_len`
  - runtime call argument setup
  - generic runtime dispatch for structural arrays

### Expected Outcome

- no `rt_array_len` call in emitted array length code
- reduced instruction count and stack traffic
- immediate speedup for length-heavy and loop-heavy code

### Tests

- update or add codegen tests asserting that structural array length emits no `rt_array_len` call
- add runtime-facing tests proving null behavior remains correct

## Slice 4: Add specialized array `for-in` emission

Status: proposed

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

- keep the existing helper locals for collection, length, and index, but specialize how they are populated and consumed for array-backed loops
- emit loop setup as:
  - evaluate collection once
  - store collection local once
  - null-check once
  - load array length once directly
  - initialize index local
- emit loop body setup as:
  - compare index against cached length
  - compute element address directly from `data + index * element_size`
  - load element into the element local
  - continue with normal lowered loop body
- preserve the generic protocol-dispatch path for non-array receivers

### Expected Outcome

- no per-iteration `rt_array_get_*` call for array-backed `for-in`
- no generic `iter_len` runtime call for array-backed `for-in`
- major speedup in array iteration kernels

### Tests

- add codegen tests proving array-backed `for-in` emits no `rt_array_len` or `rt_array_get_*` call
- add tests for primitive and reference arrays separately
- add runtime behavior tests for loop correctness, including null and bounds-relevant cases

## Slice 5: Add direct array indexed-read emission

Status: proposed

Payoff: high

Risk: medium

### Purpose

Replace `rt_array_get_*` runtime calls with direct indexed loads when the compiler already knows the receiver is a structural array.

### Where To Change

- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
- new helper module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
- optionally [compiler/semantic/lowering/executable.py](compiler/semantic/lowering/executable.py) if a lowered strategy bit is needed

### Concrete Changes

- for structural array `IndexReadExpr`:
  - evaluate receiver once
  - evaluate index once
  - preserve null semantics
  - emit inline bounds checks
  - compute direct element address
  - load the element according to its runtime representation
- keep generic runtime-dispatch reads for non-array collection receivers

### Expected Outcome

- no `rt_array_get_*` call for structural array reads
- reduced call overhead in indexing-heavy code
- better interaction with loop code and later backend cleanups

### Tests

- add codegen tests asserting direct loads instead of `rt_array_get_*` calls
- add negative tests covering out-of-bounds and null behavior
- add tests for primitive arrays and reference arrays

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

## Slice 7: Optional direct array indexed-write follow-up

Status: proposed

Payoff: medium

Risk: medium to high

### Purpose

Consider direct array writes only after length, iteration, and indexed reads are stable.

### Why This Is A Follow-Up

While the current runtime implementation for `rt_array_set_*` is direct bounds-checked mutation, writes are a more future-sensitive area if GC write barriers or additional mutation invariants are introduced later.

### Expected Outcome

- possible additional speedup for mutation-heavy kernels
- intentionally deferred to avoid coupling the initial plan to future GC write semantics

## Detailed File-Level Change Map

## `compiler/semantic/lowering/collections.py`

### Purpose

Remain the source of truth for recognizing structural array operations.

### Changes

- keep existing structural array recognition
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
- document correspondence to runtime array layout

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

Emit specialized array iteration loops from lowered array fast-path forms.

### Changes

- add direct array-backed `for-in` emission path
- keep current generic lowered `for-in` path for non-array iteration

### Expected Outcome

- no per-iteration `rt_array_get_*` call in array-backed loops

## `compiler/codegen/abi/runtime.py`

### Purpose

Remain the source of runtime-call effects and helper metadata.

### Changes

- minimal changes expected
- may gain comments or helpers clarifying which array helpers remain on the runtime path versus which are bypassed for structural arrays

### Expected Outcome

- backend policy remains centralized for actual runtime calls

## `runtime/src/array.c`

### Purpose

Remain the runtime ABI reference for array object layout and semantics.

### Changes

- no algorithmic runtime change required for the initial fast-path plan
- optional future comment updates documenting the compiler’s direct-layout dependency

### Expected Outcome

- no runtime churn required for the first rollout

## What To Test

Tests should focus on emitted structure, preserved behavior, and separation between array fast paths and generic collection/runtime paths.

## Correctness Tests

- array length still preserves null behavior
- array indexed reads still preserve bounds behavior
- array-backed `for-in` still evaluates the collection once
- array-backed `for-in` still preserves element values and iteration order
- reference-array iteration keeps the collection safely alive across the loop
- non-array collection-protocol types still go through the generic dispatch path

## Precision Tests

- structural array length emits no `rt_array_len` call
- structural array indexing emits no `rt_array_get_*` call
- structural array `for-in` emits no `rt_array_len` or `rt_array_get_*` call
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

## Measurement Strategy

This work is intended to improve runtime speed. It should therefore be measured with backend-output metrics and representative loop kernels.

Suggested metrics:

- count of emitted `rt_array_len` calls before and after
- count of emitted `rt_array_get_*` calls before and after
- total emitted instruction count for array-length, array-indexing, and array-iteration kernels
- loop body instruction count for representative `for-in` examples
- microbenchmarks for:
  - repeated `len()` on arrays
  - array iteration over primitive arrays
  - array iteration over reference arrays
  - indexed reads in tight loops

Suggested command surface can mirror existing measurement scripts if a dedicated script is later added.

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

## Ordered Implementation Checklist

1. [x] Add compiler-side array ABI helpers in a new module such as [compiler/codegen/abi/array.py](compiler/codegen/abi/array.py)
2. [x] Document the compiler/runtime array-layout dependency in code comments near the new ABI helpers
3. [ ] Extend lowered IR to carry explicit array fast-path strategy for `for-in`
4. [ ] Update executable lowering to preserve array-backed iteration strategy explicitly
5. [ ] Emit direct array length loads for `ArrayLenExpr`
6. [ ] Add codegen tests proving structural arrays no longer call `rt_array_len`
7. [ ] Emit specialized array-backed `for-in` loops without `rt_array_get_*` runtime calls
8. [ ] Add codegen and runtime tests for primitive-array iteration
9. [ ] Add codegen and runtime tests for reference-array iteration
10. [ ] Emit direct structural-array indexed reads without `rt_array_get_*` runtime calls
11. [ ] Add negative tests for null and out-of-bounds behavior under direct indexed-read fast paths
12. [ ] Confirm slice operations remain unchanged on the runtime path
13. [ ] Measure instruction-count and runtime improvements on representative collection kernels
14. [ ] Decide whether direct indexed writes are worth a follow-up plan

## Definition Of Success

This plan succeeds if, after the main slices land:

- structural array length no longer emits `rt_array_len`
- structural array-backed `for-in` no longer emits generic `iter_len` and per-iteration `iter_get` runtime calls
- structural array indexed reads no longer emit `rt_array_get_*`
- null and bounds behavior remains correct
- non-array collection protocol types continue to use the generic dispatch path unchanged
- slice operations remain correct and unchanged until a dedicated follow-up plan exists
- representative generated code is measurably smaller and faster in array-heavy kernels