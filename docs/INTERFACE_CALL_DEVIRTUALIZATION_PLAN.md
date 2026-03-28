# Interface Call Devirtualization Plan

This document defines a concrete implementation plan for devirtualizing interface method calls when the concrete receiver type is already known.

The goal is to generate faster code by rewriting some semantic interface calls into direct instance-method calls before codegen emits runtime interface lookup helpers.

This is primarily a generated-code quality plan. It is not mainly a compiler-throughput plan.

## Why This Plan Exists

The compiler already has two important optimizations in place:

- root-slot and runtime-call scaffolding in codegen has been reduced
- redundant runtime type checks are now eliminated using flow-sensitive type narrowing

That work materially lowers backend overhead, but a meaningful cost still remains in interface-heavy code: dynamic interface dispatch.

Today, even when the optimizer can already prove that a local has one exact concrete class on the current path, a call through an interface-typed receiver can still survive as a semantic interface call and later expand into:

- interface method lookup at runtime
- extra stack plumbing around the lookup path
- temporary receiver preservation and rooting
- an indirect call through the looked-up method pointer

This matters because interface-call overhead is not just one helper call. It tends to expand into a bundle of backend work, and it often appears on code paths that were already narrowed by a successful cast or type test.

The current semantic optimization pipeline therefore leaves a useful class of dynamic dispatch overhead untouched even after narrowing has proved the receiver's exact class.

## Baseline Behavior Today

The current design spans these main pieces:

- [compiler/semantic/ir.py](compiler/semantic/ir.py)
  - represents direct instance dispatch as `InstanceMethodCallTarget`
  - represents dynamic interface dispatch as `InterfaceMethodCallTarget`
  - preserves structured control flow and stable `LocalId` identity
- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
  - already tracks exact and compatible runtime facts for locals
  - can prove that a local has one exact concrete class inside a branch or after a successful cast
- [compiler/typecheck/declarations.py](compiler/typecheck/declarations.py)
  - already validates interface conformance
  - guarantees that a concrete class implementing an interface has a matching instance method by name and signature
- [compiler/semantic/lowering/expressions.py](compiler/semantic/lowering/expressions.py)
  - lowers source method calls into semantic call targets
  - preserves interface calls as `InterfaceMethodCallTarget`
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
  - lowers `InstanceMethodCallTarget` using the normal direct call path
  - lowers `InterfaceMethodCallTarget` using `rt_lookup_interface_method` followed by the actual call

Three current facts are important:

1. The semantic optimizer already has enough branch-sensitive proof machinery to know when a receiver local has one exact runtime class.
2. Semantic IR still preserves interface calls as a distinct target shape that can be rewritten before codegen.
3. Once an interface call reaches codegen, the optimization surface is worse because the direct semantic proof has already been lowered into runtime lookup mechanics.

That means this problem should be solved in semantic optimization, not in codegen.

## Core Design Goal

Add a semantic optimization pass that rewrites interface method calls to direct instance-method calls when the current control-flow state proves that the receiver local has one exact concrete class that implements the interface.

The rewrite should turn:

1. `InterfaceMethodCallTarget(interface_id=..., method_id=..., access=...)`

into:

1. `InstanceMethodCallTarget(method_id=<concrete method>, access=...)`

when the pass can prove the rewrite is correct on every path reaching that call.

## Non-Goals

- do not redesign semantic IR into SSA or CFG form
- do not move this optimization into codegen
- do not speculate on receiver types without proof
- do not try to devirtualize arbitrary receiver expressions in the first implementation
- do not combine this first slice with polymorphic inline caches or runtime profiling
- do not weaken runtime correctness for interface calls that are not statically proved monomorphic
- do not combine this first change with broader call inlining or interprocedural specialization

## Main Architectural Decisions

## 1. Implement this as a dedicated semantic pass

This should be a new pass in `compiler/semantic/optimizations/`, not a special case hidden inside `flow_sensitive_type_narrowing.py` or codegen.

Suggested file name:

- [compiler/semantic/optimizations/interface_call_devirtualization.py](compiler/semantic/optimizations/interface_call_devirtualization.py)

### Purpose

Keep responsibilities separated:

- `flow_sensitive_type_narrowing` proves runtime type facts
- interface-call devirtualization consumes those facts to rewrite dispatch
- codegen remains a straightforward lowering of semantic call target shapes

### Expected Outcome

- clearer ownership of proof generation versus call-target rewriting
- simpler tests
- a reusable place to extend devirtualization later without entangling codegen

## 2. Consume exact facts for locals only in the first slice

The first implementation should only devirtualize calls when the receiver is a local reference.

That means the pass should recognize patterns like:

- `InterfaceMethodCallTarget(access.receiver=LocalRefExpr(...))`

and should intentionally skip more complex receiver shapes in the first slice, such as:

- field reads
- index reads
- calls returning interface values
- arbitrary nested expressions that do not have stable local identity

### Purpose

Stay aligned with the current narrowing design, which already tracks facts by `LocalId`.

### Expected Outcome

- a smaller and safer first implementation
- high practical payoff anyway, because explicit cast-and-store and type-test-then-call patterns usually operate on locals

## 3. Require exact concrete class facts, not mere compatibility facts

The pass should only devirtualize when it has an exact concrete class fact for the receiver local.

Compatibility with an interface is not enough.

Examples:

- if `value` is known-compatible with `Hashable`, that does not identify one method body
- if `value` is known-exactly `main::Key`, that does identify one concrete `MethodId` for `hash_code`

### Purpose

Avoid unsound rewrites that would collapse still-polymorphic interface calls.

### Expected Outcome

- simple correctness rule
- no dependence on negative facts or speculative reasoning

## 4. Build an explicit interface implementation lookup index

The pass should not rediscover concrete methods ad hoc while walking expressions.

Add a helper that maps:

- `(ClassId, InterfaceMethodId) -> MethodId`

Suggested helper file:

- [compiler/semantic/optimizations/helpers/interface_dispatch.py](compiler/semantic/optimizations/helpers/interface_dispatch.py)

Suggested structure:

```python
@dataclass(frozen=True)
class InterfaceDispatchIndex:
    implementing_method_by_class_and_interface_method: dict[tuple[ClassId, InterfaceMethodId], MethodId]
```

Construction should use semantic program metadata:

- `SemanticClass.implemented_interfaces`
- interface method ids on `SemanticInterface`
- concrete class method ids on `SemanticClass.methods`

### Purpose

Keep interface-to-concrete method resolution explicit, testable, and reusable.

### Expected Outcome

- a simple lookup during rewriting
- less duplication between devirtualization logic and future dispatch-related optimizations

## 5. Rewrite semantic call targets, not backend call sequences

The pass should replace `InterfaceMethodCallTarget` with `InstanceMethodCallTarget` in semantic IR.

It should not emit special backend flags or ask codegen to reinterpret an interface target.

### Purpose

Let the existing direct-call code path in [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py) handle devirtualized calls automatically.

### Expected Outcome

- minimal backend churn
- smaller blast radius
- better composition with later semantic cleanup passes

## High-Level Plan

This feature should be implemented in ordered slices.

## Slice 1: Add interface implementation lookup helpers

Status: implemented

Payoff: medium

Risk: low

### Purpose

Centralize the mapping from a concrete class plus interface method to the actual class method id that should be called.

### Where To Change

- [compiler/semantic/optimizations/helpers/interface_dispatch.py](compiler/semantic/optimizations/helpers/interface_dispatch.py)

### Concrete Changes

- add `InterfaceDispatchIndex`
- build a mapping from `(ClassId, InterfaceMethodId)` to concrete `MethodId`
- match interface methods to class methods by method name within validated implementations
- raise internal errors if a validated implementation is missing the expected concrete method id

Implemented in:

- [compiler/semantic/optimizations/helpers/interface_dispatch.py](compiler/semantic/optimizations/helpers/interface_dispatch.py)

### Expected Outcome

- a single source of truth for devirtualization target resolution
- simpler devirtualization pass logic

### Tests

- add unit tests for:
  - same-module interface implementations
  - imported interfaces implemented by local classes
  - multiple implemented interfaces on one class
  - correct mapping of interface method ids to concrete method ids

Implemented in:

- [tests/compiler/semantic/optimizations/test_interface_dispatch.py](tests/compiler/semantic/optimizations/test_interface_dispatch.py)

## Slice 2: Share or expose narrowing state for consumers

Status: implemented

Payoff: high

Risk: medium

### Purpose

Make the existing exact-type facts from flow-sensitive narrowing available to the devirtualization pass without duplicating fragile branch-state logic.

### Where To Change

- either extract shared logic from [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
- or add a helper under [compiler/semantic/optimizations/helpers/](compiler/semantic/optimizations/helpers/)

Possible helper file:

- [compiler/semantic/optimizations/helpers/narrowing_state.py](compiler/semantic/optimizations/helpers/narrowing_state.py)

### Concrete Changes

- share `_TypeFacts`
- share `_NarrowState`
- share branch seeding and merge behavior
- keep the control-flow model identical to the existing narrowing pass:
  - branch-sensitive across `if`
  - conservative across loops in the first slice
  - invalidating on reassignment

Implemented in:

- [compiler/semantic/optimizations/helpers/narrowing_state.py](compiler/semantic/optimizations/helpers/narrowing_state.py)
- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Expected Outcome

- one fact model for both narrowing and devirtualization
- less duplicated reasoning

### Tests

- if state extraction happens, preserve the current narrowing tests unchanged
- add small helper-level tests for exact-type retention, branch merge, reassignment invalidation, and block-scope cleanup

Implemented in:

- [tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py](tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py)
- [tests/compiler/semantic/optimizations/test_narrowing_state.py](tests/compiler/semantic/optimizations/test_narrowing_state.py)

## Slice 3: Rewrite proven-monomorphic interface calls

Status: planned

Payoff: very high

Risk: medium

### Purpose

Replace interface dispatch with direct instance dispatch when the receiver local has one exact concrete class fact.

### Where To Change

- [compiler/semantic/optimizations/interface_call_devirtualization.py](compiler/semantic/optimizations/interface_call_devirtualization.py)

### Concrete Changes

- walk functions and methods with the same structured control-flow model used by narrowing
- when seeing a `CallExprS` with `InterfaceMethodCallTarget`:
  - require `access.receiver` to be `LocalRefExpr`
  - read current facts for that local
  - require `exact_type` to be present and class-backed
  - look up the concrete `MethodId` in `InterfaceDispatchIndex`
  - rewrite target to `InstanceMethodCallTarget(method_id=..., access=...)`
- keep arguments, return type, span, and receiver expression unchanged
- record stats such as:
  - devirtualized interface calls
  - skipped interface calls with only compatibility facts
  - skipped interface calls without local receivers

### Expected Outcome

- fewer semantic interface-call targets survive to codegen
- fewer runtime interface lookups in generated code
- direct reuse of the existing instance-method codegen path

### Tests

- add tests showing:
  - `if value is Key { return value.hash_code(); }` rewrites to `InstanceMethodCallTarget`
  - `var key: Key = (Key)obj; return key.hash_code();` rewrites to `InstanceMethodCallTarget`
  - merge points that lose exactness remain as interface calls
  - reassignment invalidates devirtualization
  - interface-compatible but not exact facts do not rewrite

## Slice 4: Re-run structural cleanup after devirtualization

Status: planned

Payoff: medium

Risk: low

### Purpose

Let the simpler direct-call shape participate in later cleanup.

### Where To Change

- [compiler/semantic/optimizations/pipeline.py](compiler/semantic/optimizations/pipeline.py)

### Concrete Changes

- place `interface_call_devirtualization` after `flow_sensitive_type_narrowing`
- keep later cleanup passes such as:
  - `redundant_cast_elimination`
  - `dead_store_elimination`
  - `constant_fold`
  - `simplify_control_flow`
  - `dead_stmt_prune`
  - `unreachable_prune`

### Expected Outcome

- devirtualized call targets become part of the normal optimized semantic program
- later cleanup continues to operate over the simplified structure

### Tests

- update pipeline tests to reflect the new pass order
- add pipeline coverage showing devirtualization composes with narrowing and later cleanup

## Recommended Initial Pass Order

The best initial order is:

1. `constant_fold`
2. `simplify_control_flow`
3. `copy_propagation`
4. `flow_sensitive_type_narrowing`
5. `interface_call_devirtualization`
6. `redundant_cast_elimination`
7. `dead_store_elimination`
8. `constant_fold`
9. `simplify_control_flow`
10. `dead_stmt_prune`
11. `unreachable_prune`

This order keeps responsibilities separated:

- alias and simplification work happen before devirtualization
- narrowing proves exact receiver facts
- devirtualization consumes those facts to rewrite call targets
- later cleanup runs over the simplified call structure

## Practical First-Implementation Scope

The first implementation should support only these high-value cases:

- interface method call whose receiver is a `LocalRefExpr`
- exact class fact introduced by a positive type-test branch
- exact class fact introduced by a successful checked cast to a class
- exact class fact propagated through existing local fact tracking

The first implementation should explicitly skip:

- field-read receivers
- indexed receivers
- arbitrary nested receiver expressions
- loop fixed-point strengthening beyond the current conservative narrowing model
- speculative multi-target dispatch splitting
- codegen-only devirtualization

That slice is still large enough to remove meaningful interface lookup overhead while staying maintainable.

## Expected Backend Impact

If this plan is implemented, later codegen in [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py) should emit fewer calls to:

- `rt_lookup_interface_method`

That should in turn reduce:

- stack plumbing around interface lookup
- temporary receiver preservation for the lookup path
- indirect call setup specific to interface dispatch
- code size in interface-heavy and cast-heavy programs

The result is not only fewer runtime helpers. It also moves the call onto the cheaper direct instance-method path that already exists in codegen.

## Risks And Correctness Constraints

The main risk is devirtualizing too aggressively.

The implementation must remain conservative around:

- merged branches where exact receiver class is not preserved on all paths
- reassignment of narrowed locals
- loop-carried state
- facts that prove interface compatibility but not one exact class
- receivers that are not locals in the first implementation
- imported interfaces and classes where method ids must still resolve correctly

A call should only be devirtualized if the pass can prove that every path reaching that call already guarantees one exact concrete receiver class.

When proof is incomplete, keep the original `InterfaceMethodCallTarget`.

## Summary

This optimization belongs in semantic IR, not codegen.

The core idea is simple:

1. use flow-sensitive narrowing facts to identify locals with one exact concrete class
2. map interface methods on that class to the concrete `MethodId`
3. rewrite semantic interface calls to direct instance-method calls
4. let the existing direct-call backend path handle the rest

That gives the compiler a direct way to remove runtime interface lookup when dynamic dispatch is already logically unnecessary.

The best first slice is intentionally narrow, but it should already produce meaningful wins in programs that use interfaces together with type tests and checked casts.