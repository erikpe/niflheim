# Flow-Sensitive Type Narrowing Plan

This document defines a concrete implementation plan for eliminating redundant runtime type checks using flow-sensitive type narrowing.

The goal is to generate faster code by proving that some semantic casts and type tests are already guaranteed to succeed, so later lowering and codegen do not emit redundant runtime helpers such as checked casts, instance-of tests, and interface lookup preconditions.

This is primarily a generated-code quality plan. It is not mainly a compiler-throughput plan.

## Why This Plan Exists

The current semantic optimizer already removes several classes of local redundancy:

- constant expressions are folded
- control flow is simplified
- aliases are propagated
- dead stores and dead statements are removed
- exact-identity casts are removed

That work is useful, but it leaves an important class of runtime overhead untouched: repeated reference compatibility checks that are already implied by earlier successful checks on the same value.

Today the compiler can still emit repeated runtime helpers for patterns such as:

- a checked cast followed by another checked cast to the same type
- a type test followed by another equivalent type test on the same local
- a branch condition that proves a local has a certain runtime-compatible type, but later expressions inside that branch still emit checked casts or type tests
- a successful checked cast that proves a local is compatible with a type on the fallthrough path, but later expressions do not reuse that fact

These redundancies matter because each surviving semantic check tends to expand into more than one backend cost:

- the runtime helper call itself
- runtime-call scaffolding in codegen
- root-slot or temp-root maintenance around the call
- extra labels and control-flow plumbing in assembly

The current semantic optimization pipeline is therefore no longer limited only by algebraic simplification. A meaningful part of the remaining backend overhead comes from semantic reference checks that are already logically known to succeed.

## Baseline Behavior Today

The current design spans these main pieces:

- [compiler/semantic/ir.py](compiler/semantic/ir.py)
  - represents checked casts as `CastExprS`
  - represents type tests as `TypeTestExprS`
  - preserves structured control flow and stable `LocalId` identity
- [compiler/semantic/operations.py](compiler/semantic/operations.py)
  - classifies casts via `CastSemanticsKind`
  - classifies type tests via `TypeTestSemanticsKind`
- [compiler/semantic/lowering/expressions.py](compiler/semantic/lowering/expressions.py)
  - lowers source casts and type tests into semantic IR nodes
- [compiler/semantic/optimizations/copy_propagation.py](compiler/semantic/optimizations/copy_propagation.py)
  - tracks local alias facts, but not proven runtime type facts
- [compiler/semantic/optimizations/redundant_cast_elimination.py](compiler/semantic/optimizations/redundant_cast_elimination.py)
  - removes only exact identity casts based on canonical type equality
- [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py)
  - lowers remaining semantic casts and type tests into runtime helpers such as:
    - `rt_checked_cast`
    - `rt_checked_cast_interface`
    - `rt_checked_cast_array_kind`
    - `rt_is_instance_of_type`
    - `rt_is_instance_of_interface`

Two current facts are important:

1. Semantic IR still has enough structure and local identity to reason about branch-local facts.
2. Once a cast or type test reaches codegen, the optimization surface is much worse because the semantic proof obligation has already been lowered into concrete runtime helper calls.

That means this problem should be solved in semantic optimization, not in codegen.

## Core Design Goal

Add a semantic optimization pass that proves and propagates positive runtime type facts for locals across structured control flow, and uses those facts to:

1. remove redundant checked casts
2. fold redundant type tests to literal booleans
3. expose follow-up simplifications such as dead branch removal and later devirtualization opportunities

## Non-Goals

- do not redesign semantic IR into SSA or CFG form
- do not move this analysis into codegen
- do not attempt general theorem proving for arbitrary expressions
- do not mutate the declared static types of locals or expressions globally
- do not rely on loop fixed-point narrowing in the first implementation
- do not combine this change with interface devirtualization in the same slice
- do not weaken runtime correctness for casts or type tests that are not statically proved redundant

## Main Architectural Decisions

## 1. Implement this as a dedicated semantic pass

This should be a new pass in `compiler/semantic/optimizations/`, not an extension hidden inside `redundant_cast_elimination.py`.

Suggested file name:

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Purpose

Keep the responsibility clear:

- `copy_propagation` tracks local identity and alias facts
- flow-sensitive narrowing tracks runtime type facts
- `redundant_cast_elimination` remains a simple structural cleanup pass

### Expected Outcome

- simpler reasoning and testing
- better pass composability
- a reusable fact engine for later interface-call devirtualization

## 2. Track facts by `LocalId`, not by arbitrary expression trees

The first implementation should only narrow locals, not arbitrary expressions.

That means the pass should recognize facts introduced or consumed through patterns like:

- `LocalRefExpr`
- `SemanticVarDecl` assigning a checked cast result to a local
- `SemanticAssign` assigning a checked cast result to a local
- `TypeTestExprS` whose operand is a `LocalRefExpr`
- `CastExprS` whose operand is a `LocalRefExpr`

It should intentionally ignore more complex shapes in the first slice, such as:

- repeated casts over field reads
- repeated casts over indexed expressions
- repeated tests over calls

### Purpose

Stay aligned with the current semantic IR design, where `LocalId` is the stable identity for intra-function reasoning.

### Expected Outcome

- a smaller and safer first implementation
- high practical payoff anyway, because repeated checks usually happen on locals

## 3. Track positive facts only in the first slice

The pass should start with positive proofs such as:

- local `x` is known-compatible with `main::Key`
- local `x` is known-compatible with `main::Hashable`
- local `x` is known-exactly `main::Key`

It should not initially try to model negative facts such as:

- local `x` is known-not `main::Key`

### Purpose

Positive facts are enough to eliminate redundant checks. Negative facts mostly matter for branch pruning and are a more complex follow-up.

### Expected Outcome

- lower implementation complexity
- better confidence in merge logic across branches

## 4. Separate exact facts from compatibility facts

The pass needs two different kinds of information:

- exact runtime type facts
- proven compatibility facts

Examples:

- after `x is Key`, `x` has an exact class fact for `Key`
- after `x is Hashable`, `x` has interface compatibility with `Hashable`, but not an exact class fact
- after `var key: Key = (Key)obj`, the fallthrough path proves `obj` is compatible with `Key`

The pass should therefore store something like:

```python
@dataclass
class _TypeFacts:
    exact_type: SemanticTypeRef | None
    compatible_types: frozenset[SemanticTypeRef]
```

Compatibility should also be derivable from exact class facts using program metadata such as `SemanticClass.implemented_interfaces`.

### Purpose

Avoid conflating “known to be this concrete class” with “known to satisfy this interface or supertype relation”.

### Expected Outcome

- correct elimination of interface checks without pretending interface facts identify exact classes
- a clean path to later direct-call devirtualization when exact class facts exist

## 5. Keep the pass structured-flow aware, not CFG-based

The pass should mirror the current style used by [compiler/semantic/optimizations/copy_propagation.py](compiler/semantic/optimizations/copy_propagation.py):

- fork state for nested blocks
- fork and merge state across `if`
- conservatively reset or weaken state across loops in the first slice

This fits the semantic IR design documented in [docs/SEMANTIC_IR_SPEC.md](docs/SEMANTIC_IR_SPEC.md), which intentionally preserves structured control flow and avoids CFG/SSA complexity.

### Purpose

Solve the optimization at the same abstraction level as the surrounding semantic passes.

### Expected Outcome

- maintainable implementation
- predictable interaction with the existing pass suite

## High-Level Plan

This feature should be implemented in ordered slices.

## Slice 1: Add compatibility-query helpers for semantic types

Status: implemented

Implementation notes:

- implemented in [compiler/semantic/optimizations/helpers/type_compatibility.py](compiler/semantic/optimizations/helpers/type_compatibility.py)
- directly covered by [tests/compiler/semantic/optimizations/test_type_compatibility.py](tests/compiler/semantic/optimizations/test_type_compatibility.py)
- exercised by downstream fact-engine tests in [tests/compiler/semantic/optimizations/test_narrowing_state.py](tests/compiler/semantic/optimizations/test_narrowing_state.py)

Payoff: medium

Risk: low

### Purpose

Centralize the logic for proving whether one semantic type implies runtime compatibility with another.

### Where To Change

- [compiler/semantic/types.py](compiler/semantic/types.py)
- or a new helper module under [compiler/semantic/optimizations/helpers/](compiler/semantic/optimizations/helpers/)

### Concrete Changes

- add helpers that answer questions like:
  - does exact type `A` imply compatibility with target `B`?
  - does class `C` implement interface `I`?
  - does exact type `A[]` imply compatibility with `Obj`?
- take `SemanticProgram` metadata into account when checking implemented interfaces
- keep all compatibility rules explicit and testable rather than embedding them inside one pass

### Expected Outcome

- a single source of truth for narrowing proofs
- less duplication in the narrowing pass and later devirtualization work

### Tests

- add unit tests for exact-class and interface-compatibility implications
- cover class, interface, array, `Obj`, and `null` cases conservatively

## Slice 2: Introduce a per-local narrowing state and branch merge model

Status: implemented

Implementation notes:

- implemented in [compiler/semantic/optimizations/helpers/narrowing_state.py](compiler/semantic/optimizations/helpers/narrowing_state.py)
- integrated into structured statement walking in [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
- directly covered by [tests/compiler/semantic/optimizations/test_narrowing_state.py](tests/compiler/semantic/optimizations/test_narrowing_state.py)
- integration behavior around merge/reset is covered by [tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py](tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py)

Payoff: high

Risk: medium

### Purpose

Create the fact engine needed to carry runtime type knowledge across statements and branches.

### Where To Change

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Concrete Changes

- add `_NarrowState` keyed by `LocalId`
- add `_TypeFacts` holding exact and compatible facts
- define conservative merge rules for `if` branches:
  - keep only facts true on all merged paths
- invalidate or replace facts on local reassignment
- drop scoped facts when block-scoped locals leave scope
- treat loops conservatively in the first implementation, similar to the current copy-propagation reset strategy

### Expected Outcome

- a reusable branch-sensitive fact system
- a disciplined place to extend narrowing later without entangling codegen

### Tests

- add unit tests for:
  - assignment invalidation
  - block-scope cleanup
  - branch intersection behavior
  - conservative loop reset behavior

## Slice 3: Seed facts from type tests in conditions

Status: implemented

Implementation notes:

- implemented in [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
- shared condition-branch state extraction lives in [compiler/semantic/optimizations/helpers/narrowing_state.py](compiler/semantic/optimizations/helpers/narrowing_state.py)
- directly covered by [tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py](tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py)
- branch-state extraction is covered by [tests/compiler/semantic/optimizations/test_narrowing_state.py](tests/compiler/semantic/optimizations/test_narrowing_state.py)

Payoff: very high

Risk: medium

### Purpose

Use branch conditions to introduce positive runtime type facts on the path where the condition holds.

### Where To Change

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Concrete Changes

- recognize `TypeTestExprS(LocalRefExpr(...), target_type_ref=...)`
- when used as an `if` condition:
  - seed the then-branch with the positive fact
- optionally also recognize `! (local is T)` and seed the else-branch with the positive fact
- in the first slice, skip more complex boolean reasoning except possibly direct logical-and chaining if it is straightforward

### Expected Outcome

- checks inside proven-positive branches start collapsing to constants or no-op casts
- later passes can simplify those branches further

### Tests

- add tests showing:
  - `if value is Hashable { return (Hashable)value; }` loses the inner checked cast
  - `if value is Key { return value is Key; }` folds the nested test to `true`
  - the fact does not incorrectly escape the branch after merge unless both branches preserve it

## Slice 4: Seed facts from successful checked casts on the fallthrough path

Status: implemented

Implementation notes:

- successful-cast fallthrough seeding is implemented in [compiler/semantic/optimizations/helpers/narrowing_state.py](compiler/semantic/optimizations/helpers/narrowing_state.py) via `update_local_facts_from_value(...)`
- structured statement integration lives in [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)
- direct source/target fact propagation and self-assignment preservation are covered by [tests/compiler/semantic/optimizations/test_narrowing_state.py](tests/compiler/semantic/optimizations/test_narrowing_state.py)
- var-decl and assignment-path behavior is covered by [tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py](tests/compiler/semantic/optimizations/test_flow_sensitive_type_narrowing.py)

Payoff: very high

Risk: medium

### Purpose

Treat a successful cast as a proof point for later statements.

This is likely the highest-value feature beyond branch tests, because explicit cast-and-store patterns are common and currently remain completely opaque to the optimizer.

### Where To Change

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Concrete Changes

- for patterns such as:
  - `var key = (Key)obj`
  - `key = (Key)obj`
- record that the source local `obj` is known-compatible with `Key` after that statement on the fallthrough path
- also record that the destination local now carries the narrowed fact
- keep this limited to casts whose operand is a local reference in the first slice

### Expected Outcome

- subsequent casts/tests on either the destination local or original local can often be removed
- repeated checked-cast ladders collapse earlier, before codegen inserts runtime helpers

### Tests

- add tests showing:
  - repeated casts after one successful cast are removed
  - later type tests after a successful cast fold to `true`
  - reassignment invalidates the fact correctly

## Slice 5: Rewrite redundant type checks

Status: implemented

Payoff: very high

Risk: medium

### Purpose

Actually eliminate the semantic nodes that no longer need runtime validation.

### Where To Change

- [compiler/semantic/optimizations/flow_sensitive_type_narrowing.py](compiler/semantic/optimizations/flow_sensitive_type_narrowing.py)

### Concrete Changes

- if state proves a `CastExprS` succeeds, rewrite it to its operand with the target type metadata preserved
- if state proves a `TypeTestExprS` succeeds, rewrite it to `LiteralExprS(BoolConstant(True), ...)`
- keep all rewrites conservative; if proof is incomplete, leave the original node intact
- record per-kind summary stats such as:
  - removed checked casts
  - folded type tests
  - seeded narrowing facts from tests
  - seeded narrowing facts from successful casts

### Expected Outcome

- fewer semantic type-check nodes survive to codegen
- fewer backend runtime helper calls are emitted
- better visibility through debug logging

### Tests

- add exact-summary log tests similar to existing optimization pass tests
- add structural tests for rewritten return expressions and condition expressions

## Slice 6: Re-run structural cleanup passes after narrowing

Status: implemented

Payoff: high

Risk: low

### Purpose

Exploit the secondary simplifications that narrowing unlocks.

### Where To Change

- [compiler/semantic/optimizations/pipeline.py](compiler/semantic/optimizations/pipeline.py)

### Concrete Changes

- place the narrowing pass after `copy_propagation`
- keep `redundant_cast_elimination` after narrowing as a cleanup pass
- add or preserve a later `simplify_control_flow` and `constant_fold` if needed so literal `true` tests become dead-branch elimination opportunities

### Expected Outcome

- removed runtime checks turn into removed control-flow and dead statements, not just smaller expressions

### Tests

- update pipeline tests to reflect the new pass order
- add integration cases showing a branch-local type test enabling downstream simplification

## Recommended Initial Pass Order

The best initial order is:

1. `constant_fold`
2. `simplify_control_flow`
3. `copy_propagation`
4. `flow_sensitive_type_narrowing`
5. `redundant_cast_elimination`
6. `dead_store_elimination`
7. `constant_fold`
8. `simplify_control_flow`
9. `dead_stmt_prune`
10. `unreachable_prune`

This order keeps the responsibilities separated:

- alias cleanup happens before narrowing
- narrowing creates proofs and removes checks
- simple cast cleanup and control-flow cleanup happen afterward

## Practical First-Implementation Scope

The first implementation should support only these high-value cases:

- direct local type test in `if` condition
- direct local checked cast in a var decl or assignment
- repeated cast on the same local after a previous successful cast
- repeated type test on the same local after a previous successful cast or test

The first implementation should explicitly skip:

- narrowing through arbitrary field reads
- narrowing through indexed expressions
- loop fixed-point narrowing
- negative fact propagation
- interface-call devirtualization

That slice is still large enough to remove meaningful runtime helper traffic while staying maintainable.

## Expected Backend Impact

If this plan is implemented, later codegen in [compiler/codegen/emitter_expr.py](compiler/codegen/emitter_expr.py) should emit fewer calls to:

- `rt_checked_cast`
- `rt_checked_cast_interface`
- `rt_checked_cast_array_kind`
- `rt_is_instance_of_type`
- `rt_is_instance_of_interface`

That should in turn reduce:

- runtime-call setup
- temp-root traffic
- labels and scaffolding around those helpers
- code size in cast-heavy and interface-heavy programs

This pass also creates a direct future bridge to devirtualization: once a local is known to have an exact concrete class inside a region, interface method calls on that local may later be rewritten to direct instance-method calls.

## Risks And Correctness Constraints

The main risk is proving compatibility too aggressively.

The implementation must remain conservative around:

- merged branches
- loop-carried state
- reassignment of narrowed locals
- distinctions between exact class facts and interface compatibility facts
- `null` behavior for casts and type tests

A fact should only eliminate a runtime check if the pass can prove that every path reaching that expression already guarantees success.

When proof is incomplete, keep the original cast or test node.

## Summary

This optimization belongs in semantic IR, not codegen.

The core idea is simple:

1. prove runtime type facts for locals from successful casts and branch-local tests
2. carry those facts through structured control flow conservatively
3. rewrite later casts and type tests when those facts already guarantee success

That gives the compiler a direct way to remove redundant runtime type checks before they become concrete backend runtime helper calls.

The best first slice is intentionally narrow, but it should already produce meaningful wins in programs that use `Obj`, interfaces, and repeated checked casts.