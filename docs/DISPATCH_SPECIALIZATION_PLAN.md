# Dispatch Specialization Plan

Status: proposed.

This document defines a concrete implementation plan for reducing dynamic dispatch overhead after inline interface dispatch, inline class virtual dispatch, and overloaded constructor selection are already in place.

The focus is not to invent new runtime machinery. The focus is to prove that some existing semantic dispatch sites are already monomorphic and to rewrite them into cheaper existing dispatch forms before codegen.

## Purpose

The compiler now has the core ingredients needed for profitable dispatch specialization:

- interface dispatch is explicit in semantic IR and emitted inline from slot-based metadata
- ordinary overridable class calls are explicit in semantic IR and emitted through inline virtual dispatch
- structural sugar for indexing, slicing, and `for ... in` is explicit in semantic IR through `SemanticDispatch`
- flow-sensitive type narrowing already proves exact runtime types for locals on some control-flow paths
- overloaded constructor resolution already picks one exact constructor body at lowering time

What is still missing is broad reuse of those proofs.

Today, the optimizer only specializes one narrow case:

- `InterfaceMethodCallTarget` on a local receiver with one proven exact class

It does not yet apply the same proof machinery to:

- `VirtualMethodCallTarget`
- structural `InterfaceDispatch`
- structural `VirtualMethodDispatch`
- constructor-produced exact class values
- exact array values that could preserve or recover array fast paths
- non-local but stable receiver expressions
- loop bodies where the receiver type remains invariant

That leaves meaningful performance on the table in code that is already semantically monomorphic.

## Desired End State

After this work:

- interface method calls rewrite to direct instance calls when exact receiver type proves one concrete implementation
- virtual method calls rewrite to direct instance calls when exact receiver type proves one concrete target
- structural interface dispatch for `[]`, `[:]`, `[]=`, `[:]=`, and `for ... in` rewrites to direct structural method dispatch when exact receiver type proves one concrete target
- structural virtual dispatch rewrites to direct structural method dispatch when exact receiver type proves one concrete target
- locals initialized from exact constructors or exact array constructors immediately carry exact-type facts without requiring a cast or type test first
- conservative receiver normalization can expose additional dispatch sites to the same proof machinery without pushing this logic into codegen
- loop bodies keep exact facts when they remain valid rather than dropping them wholesale
- array fast paths remain array-only and are preserved or recovered when the semantic dispatch shape becomes array-direct again

## Why This Should Be Done In Semantic Optimization

This work belongs in semantic optimization rather than in codegen.

Why:

- the proof inputs already exist in semantic optimization as `NarrowState` facts keyed by `LocalId`
- semantic IR already distinguishes direct, virtual, interface, and structural dispatch explicitly
- codegen already has cheap direct paths for `InstanceMethodCallTarget`, `MethodDispatch`, and `RuntimeDispatch`
- once dynamic dispatch reaches codegen, the proof context has already been lowered away into concrete lookup mechanics

The right model is:

1. prove exact receiver knowledge in semantic optimization
2. rewrite semantic dispatch nodes into cheaper semantic dispatch nodes
3. let existing codegen paths emit the cheaper form automatically

## Current State

Current relevant implementation points:

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](../compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
  - proves exact runtime types for locals after positive type tests and successful checked casts
  - resets facts conservatively across `while` and `for ... in`
- [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py)
  - rewrites `InterfaceMethodCallTarget` to `InstanceMethodCallTarget`
  - only handles local receivers
  - intentionally ignores structural dispatch and virtual class dispatch
- [compiler/semantic/optimizations/helpers/narrowing_state.py](../compiler/semantic/optimizations/helpers/narrowing_state.py)
  - only seeds exact facts from local copies and successful checked casts
  - does not seed exact facts from constructor calls or array constructors
- [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py)
  - resolves overloaded constructors to one exact `ConstructorId`
- [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py)
  - resolves structural sugar to `RuntimeDispatch`, `MethodDispatch`, `VirtualMethodDispatch`, or `InterfaceDispatch`
- [compiler/semantic/lowering/executable.py](../compiler/semantic/lowering/executable.py)
  - chooses the direct array `for ... in` lowered strategy only when semantic dispatch is already array-runtime direct
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - already emits `InstanceMethodCallTarget` as a direct named call
  - already emits `MethodDispatch` as a direct named call
  - already emits `RuntimeDispatch` through existing array/runtime fast paths
  - emits `VirtualMethodCallTarget`, `VirtualMethodDispatch`, `InterfaceMethodCallTarget`, and `InterfaceDispatch` indirectly
- [compiler/codegen/emitter_stmt.py](../compiler/codegen/emitter_stmt.py)
  - already emits specialized array-direct `for ... in` when lowering preserved that strategy

## Recommended Design

## 1. Extend Specialization By Rewriting Semantic Dispatch Shapes

Do not add codegen-only heuristics.

Rewrite these semantic forms when proof is available:

- `InterfaceMethodCallTarget` -> `InstanceMethodCallTarget`
- `VirtualMethodCallTarget` -> `InstanceMethodCallTarget`
- `InterfaceDispatch` -> `MethodDispatch`
- `VirtualMethodDispatch` -> `MethodDispatch`

Why:

- these are already the cheapest existing semantic representations
- codegen already treats them as direct call sites
- this keeps dispatch optimization explicit, testable, and composable with later passes

## 2. Keep Exact-Type Proof As The First Correctness Gate

The first implementation slices should require a proven exact runtime type.

Compatibility alone is not enough.

Why:

- exact class facts identify one concrete method body
- compatibility facts only prove that a dynamic call is legal, not that it is monomorphic
- this matches the current correctness rule already used by interface-call devirtualization

## 3. Reuse Existing Mapping Helpers For Interface Rewrites

Continue using [compiler/semantic/optimizations/helpers/interface_dispatch.py](../compiler/semantic/optimizations/helpers/interface_dispatch.py) as the source of truth for:

- `(ClassId, InterfaceMethodId) -> MethodId`

Extend helper coverage only where structural dispatch needs additional shared lookup helpers.

Why:

- it avoids ad hoc method-body lookup in multiple passes
- the same helper can drive call-target and structural-dispatch rewriting

## 4. Seed Exact Facts From More Exact Producers

Extend narrowing so exact facts are created not only from casts and type tests, but also from values that are already exact by construction.

The first concrete producers should be:

- `ConstructorCallTarget`
- `ArrayCtorExprS`
- direct local copies of values already known exact

Why:

- constructor overload resolution already picks one exact `ConstructorId`
- array constructors already produce an exact array runtime shape
- this exposes more monomorphic receivers without adding new runtime checks

## 5. Preserve Structural Sugar As Structural Nodes

Do not lower structural sugar into ordinary method calls as part of this work.

Keep:

- `IndexReadExpr`
- `SliceReadExpr`
- `IndexLValue`
- `SliceLValue`
- `SemanticForIn`

Only rewrite their `dispatch` payloads.

Why:

- array fast paths already depend on these nodes
- `for ... in` evaluate-once and snapshotted-length semantics already depend on these nodes
- a dispatch-only rewrite is lower-risk and preserves the existing codegen structure

## 6. Recover Array Fast Paths Only Through Proven Array Dispatch Shapes

Do not teach codegen to guess arrays from arbitrary proof state.

If a prior semantic pass can safely rewrite a structural operation back to array-runtime direct dispatch, then existing lowering/codegen should pick that up naturally.

Why:

- array fast paths are already well-tested and array-only
- this preserves the current boundary between semantic proof and backend emission

## 7. Defer Closed-World Monomorphism Until After Exact-Type Slices Land

A later slice may specialize calls even without local exact facts when whole-program analysis proves that every reachable implementation collapses to one method body.

That should remain a follow-up slice.

Why:

- it is materially higher risk than exact-type-based specialization
- it couples optimization more tightly to hierarchy analysis and future language evolution
- it is not needed to unlock the most obvious wins

## What Should Change, And Where

## Semantic Optimization Helpers

- [compiler/semantic/optimizations/helpers/narrowing_state.py](../compiler/semantic/optimizations/helpers/narrowing_state.py)
  - seed exact facts from exact producers such as constructor calls and array constructors
  - add helper(s) to query exact class or exact array facts for rewritten receivers
- [compiler/semantic/optimizations/helpers/interface_dispatch.py](../compiler/semantic/optimizations/helpers/interface_dispatch.py)
  - continue mapping interface methods to concrete implementing methods
  - extend with any small shared helper needed by structural dispatch rewriting
- [compiler/semantic/optimizations/helpers/type_compatibility.py](../compiler/semantic/optimizations/helpers/type_compatibility.py)
  - preserve exact-array and exact-class compatibility behavior needed by the new fact seeding

## Semantic Optimization Passes

- [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py)
  - broaden the pass so it can also rewrite:
    - `VirtualMethodCallTarget`
    - `InterfaceDispatch`
    - `VirtualMethodDispatch`
  - keep the proof rule exact-type-based in the first slices
  - keep local-receiver-only behavior in the first slices unless and until receiver normalization lands
- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](../compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
  - preserve and merge the new exact facts seeded from constructors and arrays
  - later slice: retain facts across loops when they are not invalidated
- [compiler/semantic/optimizations/pipeline.py](../compiler/semantic/optimizations/pipeline.py)
  - keep specialization after narrowing
  - if receiver normalization becomes a dedicated pass, place it before narrowing and specialization

## Semantic Lowering

- [compiler/semantic/lowering/calls.py](../compiler/semantic/lowering/calls.py)
  - no dispatch redesign expected
  - validate that constructor lowering exposes enough exact information through `type_ref` and `ConstructorId`
- [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py)
  - no dispatch redesign expected for the first slices
  - later slice: only if needed, add a helper that can reconstruct array-runtime direct dispatch from proven exact array receiver facts
- [compiler/semantic/lowering/executable.py](../compiler/semantic/lowering/executable.py)
  - validate that rewritten `RuntimeDispatch` and `MethodDispatch` values automatically preserve or improve lowered `for ... in` strategy selection
- [compiler/semantic/lowering/statements.py](../compiler/semantic/lowering/statements.py)
  - no dispatch redesign expected
  - validate that `super(...)` stays on direct constructor-init lowering and is unaffected by specialization work

## Codegen

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - no primary redesign expected
  - direct call wins should fall out automatically once semantic targets/dispatch shapes are rewritten
- [compiler/codegen/emitter_stmt.py](../compiler/codegen/emitter_stmt.py)
  - no primary redesign expected
  - validate that structural rewrites to `MethodDispatch` or `RuntimeDispatch` reduce indirect dispatch and preserve array-direct loops

## Tests

- [tests/compiler/semantic/optimizations/test_interface_call_devirtualization.py](../tests/compiler/semantic/optimizations/test_interface_call_devirtualization.py)
  - extend existing coverage for broader specialization cases
- [tests/compiler/semantic/optimizations/test_pipeline.py](../tests/compiler/semantic/optimizations/test_pipeline.py)
  - add end-to-end semantic-pipeline coverage proving pass ordering still enables specialization
- [tests/compiler/semantic/test_lowering.py](../tests/compiler/semantic/test_lowering.py)
  - keep the baseline lowering expectations for dynamic dispatch shapes before optimization
- [tests/compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
  - assert specialized call sites no longer emit virtual or interface lookup sequences
- [tests/compiler/codegen/test_emitter_stmt.py](../tests/compiler/codegen/test_emitter_stmt.py)
  - assert specialized structural writes and `for ... in` protocol calls no longer emit indirect dispatch when proof exists
- [tests/golden/lang/test_virtual_dispatch](../tests/golden/lang/test_virtual_dispatch)
  - later slice if needed: keep behavior coverage while proving optimized dispatch still selects the same override
- [tests/golden/lang/test_indexing_sugar](../tests/golden/lang/test_indexing_sugar)
  - later slice if needed: keep interface/class structural behavior coverage stable under specialization
- [tests/golden/lang/test_for_in](../tests/golden/lang/test_for_in)
  - later slice if needed: keep iteration semantics stable under specialization

## Ordered Implementation Checklist

## Slice 1: Seed Exact Facts From Exact Producers

- [x] extend [compiler/semantic/optimizations/helpers/narrowing_state.py](../compiler/semantic/optimizations/helpers/narrowing_state.py) so `update_local_facts_from_value(...)` recognizes constructor-call results as exact concrete classes
- [x] extend [compiler/semantic/optimizations/helpers/narrowing_state.py](../compiler/semantic/optimizations/helpers/narrowing_state.py) so `update_local_facts_from_value(...)` recognizes `ArrayCtorExprS` results as exact arrays
- [x] validate that local copies preserve those facts unchanged

Test:

- [x] add focused narrowing tests showing locals initialized from exact constructor calls carry exact class facts
- [x] add focused narrowing tests showing locals initialized from exact array constructors carry exact array facts
- [x] run focused semantic optimization tests for narrowing and pipeline composition

## Slice 2: Specialize Structural Interface Dispatch

- [ ] extend [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py) so it rewrites `InterfaceDispatch` on `IndexReadExpr`, `SliceReadExpr`, `IndexLValue`, `SliceLValue`, and `SemanticForIn`
- [ ] reuse [compiler/semantic/optimizations/helpers/interface_dispatch.py](../compiler/semantic/optimizations/helpers/interface_dispatch.py) to map exact class plus interface method to concrete `MethodId`
- [ ] rewrite proven monomorphic structural interface dispatch to `MethodDispatch`

Test:

- [ ] add optimization tests proving interface-typed structural sugar rewrites from `InterfaceDispatch` to `MethodDispatch` inside exact-type regions
- [ ] add codegen tests proving specialized structural interface reads, writes, and `for ... in` calls no longer emit interface-table lookup sequences
- [ ] run focused semantic optimization and codegen tests for structural sugar

## Slice 3: Specialize Virtual Class Dispatch

- [ ] extend [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py) so it also rewrites `VirtualMethodCallTarget` to `InstanceMethodCallTarget` when exact receiver type is proven
- [ ] extend the same pass so it rewrites structural `VirtualMethodDispatch` to `MethodDispatch` when exact receiver type is proven
- [ ] reuse the existing `selected_method_id` already carried on virtual semantic nodes rather than recomputing method selection

Test:

- [ ] add optimization tests proving virtual method calls collapse to direct instance calls inside exact-type regions
- [ ] add optimization tests proving structural virtual dispatch collapses to `MethodDispatch` inside exact-type regions
- [ ] add codegen tests proving specialized class-virtual sites no longer emit vtable lookups

## Slice 4: Broaden Receivers Beyond Existing Local-Only Cases

- [ ] decide whether to extend [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py) directly or to add a small receiver-normalization pass that hoists stable receivers into temporaries
- [ ] support at least one additional safe receiver form beyond `LocalRefExpr`, preferably field reads or other effect-stable expressions first
- [ ] preserve source semantics and evaluation order; do not speculate on effectful receiver expressions

Test:

- [ ] add optimization tests covering field-read receivers or other newly supported receiver shapes
- [ ] add regression tests proving effectful or unstable receiver expressions are not incorrectly specialized

## Slice 5: Preserve Proven Facts Across Loops Conservatively

- [ ] update [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](../compiler/semantic/optimizations/flow_sensitive_type_narrowing.py) so loop handling preserves exact facts for locals that are not invalidated by the loop body
- [ ] update [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py) so it consumes those loop-preserved facts rather than resetting to empty state for loop bodies
- [ ] keep the first implementation conservative; a fixed-point widening is acceptable later, but not required for the first slice

Test:

- [ ] add optimization tests proving monomorphic interface and virtual dispatch inside loops becomes direct when loop bodies do not invalidate the receiver fact
- [ ] add regression tests proving reassignment inside the loop still blocks specialization

## Slice 6: Recover Or Preserve Array Fast Paths When Proof Allows It

- [ ] inspect whether specialization from exact array facts can safely rewrite eligible structural nodes to array `RuntimeDispatch`
- [ ] if safe and useful, add a narrowly scoped rewrite that preserves current array-only semantics
- [ ] validate that [compiler/semantic/lowering/executable.py](../compiler/semantic/lowering/executable.py) then selects `ARRAY_DIRECT` automatically for eligible `for ... in` loops

Test:

- [ ] add semantic optimization tests proving eligible array-backed structural nodes become array runtime dispatch
- [ ] add codegen tests proving array-direct `for ... in` is preserved or recovered after specialization
- [ ] run focused collection fast-path and structural-sugar test selections

## Slice 7: Optional Closed-World Monomorphic Dispatch Follow-Up

- [ ] add a separate whole-program analysis that identifies interface or virtual dispatch sites whose reachable implementations collapse to one method body even without local exact facts
- [ ] keep this analysis separate from the exact-type-based slices above
- [ ] only rewrite when every reachable implementation agrees on the same target method body

Test:

- [ ] add dedicated optimization tests covering monomorphic-by-hierarchy sites without local exact facts
- [ ] add regression tests proving polymorphic sites remain dynamic

## Validation Checklist

- [ ] flow-sensitive narrowing still preserves existing cast and type-test optimizations
- [ ] interface-call devirtualization still handles its current local-receiver cases
- [ ] specialized structural interface dispatch sites emit direct calls
- [ ] specialized virtual dispatch sites emit direct calls
- [ ] array fast paths remain array-only and behaviorally unchanged
- [ ] overloaded constructor selection behavior remains unchanged
- [ ] semantic optimization pipeline ordering still produces the expected specialized forms
- [ ] focused codegen tests for call and structural dispatch still pass
- [ ] focused golden coverage for virtual dispatch and structural sugar still passes if touched

## Non-Goals

This plan does not include:

- moving dispatch specialization into codegen heuristics
- speculative specialization without semantic proof
- polymorphic inline caches or profiling-driven dispatch selection
- interprocedural inlining of specialized targets
- changing source-language dispatch semantics
- making arrays implement user-visible interfaces as part of this optimization work
- redesigning constructor lowering or overload resolution semantics

## Recommended Implementation Order

Implement this in the order above.

The critical sequencing is:

1. improve exact-fact seeding first
2. reuse those facts for structural interface specialization
3. extend the same idea to virtual dispatch
4. only then broaden receiver shapes and loop reasoning
5. keep closed-world monomorphism as a separate follow-up

That order gives the highest payoff first while keeping each slice locally testable and preserving the existing split between semantic proof and backend emission.