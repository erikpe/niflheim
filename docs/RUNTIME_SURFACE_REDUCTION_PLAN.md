# Runtime Surface Reduction Plan

This document defines a concrete follow-up plan for reducing the remaining C runtime helper surface after inline class virtual dispatch and inline interface dispatch.

## Purpose

The interface-dispatch work already removed one important runtime boundary: interface method lookup is no longer performed by a C helper on the hot path.

That left two kinds of remaining runtime surface:

- transitional ABI and metadata that are no longer semantically required
- helper calls that still exist even though codegen now has enough metadata to emit the same fast path inline

The goal of this plan is to reduce that remaining surface in a disciplined order:

1. remove dead transitional interface ABI first
2. inline the easiest remaining slot-table-based checks next
3. inline the next-smallest array-kind runtime check after that
4. only then consider larger metadata redesigns for class cast/type-test performance

This plan is intentionally conservative. It prioritizes changes that improve clarity and shrink the runtime ABI without forcing a premature redesign of allocation, GC, or stdlib/runtime boundaries.

## Recommended Priority

## 1. Remove The Transitional Legacy Interface ABI

Summary:

- remove `RtInterfaceImpl`
- remove `RtType.legacy_interfaces`
- remove `RtType.legacy_interface_count`
- stop emitting legacy compact interface-impl arrays

Complexity:

- low to moderate

Expected benefit:

- simpler runtime ABI
- smaller emitted metadata
- fewer transitional concepts in tests and docs

Why first:

- the runtime no longer uses this metadata for dispatch, casts, or type tests
- it is now compatibility baggage rather than active behavior

## 2. Inline Interface Casts And Interface Type Tests

Summary:

- inline `Obj -> Interface` checked casts using `RtType.interface_tables[slot_index]`
- inline `obj is Interface` checks using the same slot-table path
- remove `rt_checked_cast_interface(...)` and `rt_is_instance_of_interface(...)` if nothing else still needs them

Complexity:

- low to moderate

Expected benefit:

- modest runtime win on interface-heavy cast/test code
- smaller runtime call surface
- tighter alignment between interface dispatch and interface compatibility checks

Why second:

- this uses the same metadata and same decision structure already proven by inline interface dispatch
- it is mostly emitter work, not a new runtime design

## 3. Inline Array-Kind Casts

Summary:

- inline `Obj -> T[]` runtime kind checks
- remove `rt_checked_cast_array_kind(...)` if codegen no longer uses it

Complexity:

- low to moderate

Expected benefit:

- modest runtime win on array cast paths
- one fewer runtime helper in the checked-cast family

Why third:

- it is structurally similar to interface cast/type-test inlining
- it benefits from the existing direct array ABI helpers already used by collection fast paths

## 4. Revisit Class Cast And Type-Test Lowering

Summary:

- decide whether the current `super_type` chain walk should remain in the runtime
- if profiling justifies it, either inline the existing walk or introduce better subtype metadata

Complexity:

- moderate for naive inline chain walking
- high for a real metadata redesign such as subtype ranges, ancestry bitsets, or compact class ids with interval checks

Expected benefit:

- moderate only if checked class casts and class type tests are common in real programs

Why last:

- unlike interface dispatch/casts, the current class helper path is already semantically simple and not obviously the dominant cost
- a shallow inline version removes the helper call but duplicates loop logic without changing the asymptotics

## Explicit Non-Goals For This Plan

These are not recommended in this plan:

- inlining `rt_alloc_obj(...)`
- inlining root-stack helpers such as `rt_push_roots(...)` or `rt_pop_roots(...)`
- removing stdlib-facing file IO helpers from `runtime/include/io.h`
- flattening interface method tables into a single global interface vtable

Reasons:

- those are runtime-service boundaries rather than narrow lookup helpers
- they carry materially higher correctness risk
- they would blur this cleanup plan into allocator, GC, or stdlib ABI redesign work

## Current State

Current relevant state in the repository:

- interface method calls are emitted inline in [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- class virtual calls are emitted inline through `RtType.class_vtable`
- direct array fast paths already bypass some runtime helpers for `len`, index reads, index writes, and direct array `for in`
- interface casts and interface type tests still call runtime helpers
- array-kind checked casts still call a runtime helper
- class checked casts and class type tests still call runtime helpers
- emitted `RtType` records still carry transitional legacy interface metadata fields

## What Should Change, And Where

## Runtime ABI And Metadata Cleanup

- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - remove `RtInterfaceImpl` if no remaining runtime/test code requires it
  - remove `RtType.legacy_interfaces`
  - remove `RtType.legacy_interface_count`
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - stop emitting legacy interface-impl arrays
  - remove legacy interface fields from emitted `RtType` records
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
  - update any `RtType` field offsets affected by the ABI cleanup
- [tests/runtime/test_interface_metadata.c](../tests/runtime/test_interface_metadata.c)
  - stop asserting preservation of transitional legacy metadata
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
  - update emitted `RtType` layout expectations

## Interface Cast And Type-Test Inlining

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - inline `rt_checked_cast_interface(...)`
  - inline `rt_is_instance_of_interface(...)`
  - preserve current null and bad-cast behavior
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
  - reuse or extend slot-table and interface-descriptor operand helpers
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - remove retired interface cast/type-test helpers if no longer used
- [runtime/include/runtime.h](../runtime/include/runtime.h)
  - remove retired helper declarations if codegen no longer uses them
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
  - update expectations from helper calls to inline checks
- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)
  - ensure end-to-end cast/type-test behavior still matches current semantics

## Array-Kind Cast Inlining

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - inline the object kind check for `Obj -> T[]`
- [compiler/codegen/abi/array.py](../compiler/codegen/abi/array.py)
  - expose any missing ABI constants needed for direct array-kind checks
- [runtime/src/array.c](../runtime/src/array.c)
  - remove `rt_checked_cast_array_kind(...)` if it becomes unused
- [runtime/include/array.h](../runtime/include/array.h)
  - remove the retired declaration if codegen no longer uses it
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
  - update helper-call expectations
- [tests/compiler/integration](../tests/compiler/integration)
  - keep array cast runtime coverage green

## Class Cast And Type-Test Rework

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - either inline the current `super_type` walk or switch to improved subtype metadata
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py)
  - add new subtype metadata if the redesign route is chosen
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
  - emit any new class-subtyping metadata
- [runtime/src/runtime.c](../runtime/src/runtime.c)
  - remove or simplify `rt_checked_cast(...)` / `rt_is_instance_of_type(...)` if codegen fully subsumes them
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
  - update call-vs-inline expectations
- [tests/compiler/integration](../tests/compiler/integration)
  - preserve subtype cast and type-test behavior across inheritance chains

## Ordered Implementation Checklist

## Slice 1: Remove Transitional Legacy Interface Metadata

- [x] remove `RtInterfaceImpl` from the public runtime ABI if nothing still needs it
- [x] remove `legacy_interfaces` and `legacy_interface_count` from `RtType`
- [x] stop emitting legacy interface-impl arrays in codegen
- [x] update docs and tests to treat slot tables as the only canonical interface metadata

Change:

- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py)
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
- [tests/runtime/test_interface_metadata.c](../tests/runtime/test_interface_metadata.c)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
- [docs/ABI_NOTES.md](../docs/ABI_NOTES.md)
- [docs/INTERFACES_V1.md](../docs/INTERFACES_V1.md)

Test:

- runtime metadata harness still passes
- emitted `RtType` layout tests pass
- full interface dispatch/cast tests stay green after the ABI field removal

## Slice 2: Inline Interface Casts And Interface Type Tests

- [ ] inline interface checked-cast lowering from slot-table metadata
- [ ] inline interface type-test lowering from slot-table metadata
- [ ] preserve current null-return, bool-result, and bad-cast behavior
- [ ] remove helper declarations/implementations if no longer used

Change:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [compiler/codegen/abi/object.py](../compiler/codegen/abi/object.py)
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)

Test:

- assert `Obj -> Interface` casts no longer emit `call rt_checked_cast_interface`
- assert `obj is Interface` no longer emits `call rt_is_instance_of_interface`
- integration tests still pass for successful and failing interface casts/type tests

## Slice 3: Inline Array-Kind Casts

- [ ] inline `Obj -> T[]` runtime kind checks in codegen
- [ ] preserve current null and bad-cast behavior
- [ ] remove `rt_checked_cast_array_kind(...)` if no longer used

Change:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [compiler/codegen/abi/array.py](../compiler/codegen/abi/array.py)
- [runtime/src/array.c](../runtime/src/array.c)
- [runtime/include/array.h](../runtime/include/array.h)
- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)

Test:

- assert `Obj -> T[]` casts no longer emit `call rt_checked_cast_array_kind`
- integration tests for valid and invalid array casts still pass

## Slice 4: Decide The Class Cast/Type-Test Strategy

- [ ] measure or inspect whether class cast/type-test helpers are worth attacking next
- [ ] if not worth it, explicitly keep them as runtime helpers and stop this plan here
- [ ] if worth it, choose between inline `super_type` walking and a better subtype metadata design
- [ ] implement the chosen design with focused tests only after the metadata decision is explicit

Change:

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [compiler/codegen/metadata.py](../compiler/codegen/metadata.py) if subtype metadata changes
- [compiler/codegen/emitter_module.py](../compiler/codegen/emitter_module.py) if subtype metadata changes
- [runtime/src/runtime.c](../runtime/src/runtime.c)
- [runtime/include/runtime.h](../runtime/include/runtime.h)

Test:

- assert class checked casts and class type tests preserve current inheritance semantics
- assert deeper inheritance chains remain correct
- compare generated code only after the metadata strategy is settled

## Suggested Validation Strategy

After each completed slice, run the smallest relevant scope first, then widen.

Focused checks:

- [tests/compiler/codegen/test_emit_asm_casts_metadata.py](../tests/compiler/codegen/test_emit_asm_casts_metadata.py)
- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)
- [tests/runtime/test_interface_metadata.c](../tests/runtime/test_interface_metadata.c)
- [tests/runtime/test_interface_casts.c](../tests/runtime/test_interface_casts.c)
- [tests/runtime/test_interface_casts_negative.c](../tests/runtime/test_interface_casts_negative.c)
- [tests/runtime/test_interface_dispatch.c](../tests/runtime/test_interface_dispatch.c)
- [tests/runtime/test_interface_dispatch_negative.c](../tests/runtime/test_interface_dispatch_negative.c)

Wider checks:

- full pytest suite
- `make -C runtime test-all`

## Success Criteria

This plan is complete when:

- transitional legacy interface metadata is removed from the runtime ABI and emitted metadata
- interface casts and interface type tests no longer require runtime helper calls
- array-kind casts no longer require a runtime helper call
- class cast/type-test remaining helper usage is either explicitly retained by decision or replaced by a better-documented design
- runtime behavior and diagnostics remain unchanged for successful casts, failed casts, and null handling