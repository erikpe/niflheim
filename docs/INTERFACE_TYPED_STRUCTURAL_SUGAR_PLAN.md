# Interface-Typed Structural Sugar Plan

Status: proposed.

This document defines a concrete implementation plan for fully supporting interface-typed structural sugar for indexing, slicing, and `for ... in`.

## Purpose

The language design already intends structural sugar to work through method-shaped protocols rather than through hard-coded container names:

- `value[index]` should lower through `index_get(...)`
- `value[index] = rhs` should lower through `index_set(...)`
- `value[begin:end]` should lower through `slice_get(...)`
- `value[begin:end] = rhs` should lower through `slice_set(...)`
- `for elem in value` should lower through `iter_len()` and `iter_get(i64)`

That behavior already works for:

- arrays through built-in runtime and fast-path lowering
- concrete class-typed receivers through structural method resolution

It does not yet work when the receiver's static type is an interface, even when that interface declares the required methods.

The goal of this change is to close that implementation gap without redesigning the language model, runtime ABI, or existing array fast paths.

## Desired End State

After this change:

- interface-typed `value[index]` uses interface dispatch when the interface declares a compatible `index_get(K) -> R`
- interface-typed `value[index] = rhs` uses interface dispatch when the interface declares a compatible `index_set(K, V) -> unit`
- interface-typed `value[begin:end]` and `value[begin:end] = rhs` use interface dispatch when the interface declares compatible `slice_get` and `slice_set` methods
- interface-typed `for ... in` uses interface dispatch when the interface declares compatible `iter_len() -> u64` and `iter_get(i64) -> T` methods
- arrays keep their existing built-in fast paths
- concrete class receivers keep their existing direct or virtual structural dispatch
- explicit interface method calls and structural interface sugar share the same dispatch model

## Current State

Current implementation points:

- [docs/SUGARING_DESIGN.md](../docs/SUGARING_DESIGN.md)
  - documents that interface-typed `for ... in` is intended but not implemented
- [docs/TODO.md](../docs/TODO.md)
  - tracks interface-typed indexing, slice, and iteration sugar as missing work
- [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
  - resolves structural protocols only for arrays and classes
  - rejects interface-typed receivers before dispatch lowering can occur
- [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py)
  - resolves collection dispatch only to `RuntimeDispatch`, `MethodDispatch`, or `VirtualMethodDispatch`
  - has no interface-dispatch variant for structural sugar
- [compiler/typecheck/calls.py](../compiler/typecheck/calls.py)
  - already supports explicit interface method calls
- [compiler/semantic/lowering/resolution.py](../compiler/semantic/lowering/resolution.py)
  - already resolves explicit interface method member access
- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - already emits interface method calls through slot-based interface table lookup

That means the missing behavior is not a parser problem or a runtime ABI problem. It is a structural typecheck and dispatch-selection gap.

## Recommended Design

## 1. Extend Structural Dispatch Rather Than Rewriting Sugar As Plain Calls

Keep the existing structural IR nodes and extend their dispatch payload.

Why:

- `IndexReadExpr`, `SliceReadExpr`, `IndexLValue`, `SliceLValue`, and `SemanticForIn` already encode the right semantics
- array fast paths are already built around these nodes
- for-in evaluate-once and length-snapshot behavior already depends on this structure
- assignment sugar is already modeled as lvalues rather than synthetic call statements

Do not replace structural sugar with a lowering rewrite into general `CallExprS` nodes for all non-array receivers.

## 2. Add An Interface Dispatch Variant To `SemanticDispatch`

Recommended new IR shape in [compiler/semantic/ir.py](../compiler/semantic/ir.py):

```python
@dataclass(frozen=True)
class InterfaceDispatch:
    interface_id: InterfaceId
    method_id: InterfaceMethodId


SemanticDispatch = RuntimeDispatch | MethodDispatch | VirtualMethodDispatch | InterfaceDispatch
```

Why:

- structural sugar already dispatches through a compact `SemanticDispatch` union
- codegen already knows how to emit interface lookup from `interface_id` and `method_id`
- this keeps structural reads, writes, and loops uniform across arrays, classes, and interfaces

## 3. Teach Structural Typechecking To Validate Interface Protocols

Structural protocol checks in [compiler/typecheck/structural.py](../compiler/typecheck/structural.py) should accept interface-typed receivers as well as class-typed receivers.

Recommended rules:

- `index_get` must be an instance method with exactly one parameter
- `index_set` must be an instance method with exactly two parameters and return `unit`
- `slice_get` must be an instance method with two `i64` parameters
- `slice_set` must be an instance method with `i64`, `i64`, and value parameters and return `unit`
- `iter_len` must be an instance method with zero parameters and return `u64`
- `iter_get` must be an instance method with one `i64` parameter

For interfaces, these checks should read from `InterfaceInfo.methods` instead of `ClassInfo.methods`.

Important constraint:

- keep current diagnostics as specific as possible
- preserve existing array behavior and array-specific index validation

## 4. Resolve Structural Interface Sugar To Interface Dispatch

Update [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py) so `resolve_collection_dispatch(...)` returns:

- `RuntimeDispatch` for arrays
- `MethodDispatch` or `VirtualMethodDispatch` for class receivers
- `InterfaceDispatch` for interface receivers

The dispatch choice should be driven by the receiver's checked type, not by syntactic form.

Important constraint:

- structural sugar should follow the receiver's nominal dispatch model
- explicit interface calls and structural interface sugar should use the same interface table metadata

## 5. Reuse Existing Interface Codegen For Structural Sugar

Update [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py) so `_emit_dispatch_call(...)` understands `InterfaceDispatch`.

Recommended behavior:

1. treat the first call argument as the receiver, just like virtual structural dispatch does today
2. reuse the existing interface-table lookup helpers already used by `InterfaceMethodCallTarget`
3. perform the same indirect-call sequence as ordinary interface method calls

This change should apply automatically to:

- index reads
- slice reads
- index writes
- slice writes
- `for ... in` protocol calls

## 6. Update Dispatch Consumers That Assume Only Runtime Or Class Methods

Several downstream helpers currently assume that structural dispatch is only:

- runtime dispatch, or
- concrete class method dispatch

Those helpers must be updated to recognize `InterfaceDispatch`.

Required areas:

- temp-root sizing and rooted-argument analysis
- GC-effect analysis
- reachability and pruning

Important constraint:

- interface-typed structural sugar must not be pruned as unreachable merely because it does not carry a concrete `MethodId`

## 7. Keep Array Fast Paths Intact

This plan must not regress the existing array fast-path behavior.

Non-negotiable preserved behavior:

- direct array len/index/for-in fast paths remain array-only
- interface-typed structural sugar uses interface dispatch, not array runtime dispatch, even when the dynamic receiver happens to be an array-like class
- no runtime ABI change is needed for this feature

## What Should Change, And Where

## Semantic IR And Dispatch Modeling

- [compiler/semantic/ir.py](../compiler/semantic/ir.py)
  - add `InterfaceDispatch`
  - extend `SemanticDispatch`
  - update `dispatch_method_id(...)` or add a parallel interface-dispatch accessor if needed by reachability code

## Structural Typechecking

- [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
  - extend `resolve_for_in_element_type(...)` to support interface receivers
  - extend `resolve_index_expression_type(...)` to support interface receivers
  - extend index assignment protocol checks to support interface receivers
  - extend slice protocol inference helpers to support interface receivers
  - factor shared protocol-signature checking so class and interface logic do not drift
- [compiler/typecheck/module_lookup.py](../compiler/typecheck/module_lookup.py)
  - reuse `lookup_interface_by_type_name(...)` where structural helpers currently only use class lookup

## Structural Lowering

- [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py)
  - return `InterfaceDispatch` for interface receivers in `resolve_collection_dispatch(...)`
  - keep array and class behavior unchanged
- [compiler/semantic/lowering/statements.py](../compiler/semantic/lowering/statements.py)
  - no design change expected, but validate that `for ... in` picks up the new dispatch automatically
- [compiler/semantic/lowering/expressions.py](../compiler/semantic/lowering/expressions.py)
  - no design change expected beyond consuming the new dispatch variant through existing collection nodes

## Codegen

- [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
  - extend `_emit_dispatch_call(...)` for `InterfaceDispatch`
  - reuse interface slot and interface method slot lookup helpers already used for ordinary interface calls
- [compiler/codegen/emitter_stmt.py](../compiler/codegen/emitter_stmt.py)
  - no structural redesign expected
  - validate that index and slice writes work through `_emit_dispatch_call(...)` once `InterfaceDispatch` is added
- [compiler/codegen/layout.py](../compiler/codegen/layout.py)
  - update `_dispatch_reference_arg_indices(...)` and any call-root sizing helpers to recognize `InterfaceDispatch`
- [compiler/codegen/effects.py](../compiler/codegen/effects.py)
  - treat `InterfaceDispatch` as potentially GC-executing, same as other method dispatch
- [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py)
  - no major redesign expected
  - validate that liveness accounting remains correct when structural dispatch is interface-based

## Semantic Optimizations

- [compiler/semantic/optimizations/unreachable_prune.py](../compiler/semantic/optimizations/unreachable_prune.py)
  - ensure interface-dispatched structural sugar keeps the relevant interface reachable
  - ensure implementing methods are retained via the existing interface reachability path
- [compiler/semantic/optimizations/interface_call_devirtualization.py](../compiler/semantic/optimizations/interface_call_devirtualization.py)
  - no correctness change required for initial support
  - optional follow-up: teach the pass to devirtualize `InterfaceDispatch` in structural sugar the same way it devirtualizes `InterfaceMethodCallTarget`

## Tests

- [tests/compiler/typecheck/test_structural.py](../tests/compiler/typecheck/test_structural.py)
  - add positive interface-typed index, index assignment, slice, slice assignment, and for-in cases
  - add targeted negative cases for missing methods and wrong signatures on interfaces
- [tests/compiler/semantic/test_lowering.py](../tests/compiler/semantic/test_lowering.py)
  - add assertions that interface-typed sugar lowers to `InterfaceDispatch`
  - preserve existing expectations for arrays and class receivers
- [tests/compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
  - verify interface-typed index and slice reads emit interface dispatch rather than runtime or virtual dispatch
- [tests/compiler/codegen/test_emitter_stmt.py](../tests/compiler/codegen/test_emitter_stmt.py)
  - verify interface-typed index and slice writes and `for ... in` protocol calls emit interface dispatch correctly
- [tests/compiler/semantic/optimizations/test_unreachable_prune.py](../tests/compiler/semantic/optimizations/test_unreachable_prune.py)
  - add coverage that structural interface sugar keeps interface reachability alive
- [tests/golden/lang/test_indexing_sugar](../tests/golden/lang/test_indexing_sugar)
  - add positive interface-typed indexing and slice cases
- [tests/golden/lang/test_for_in](../tests/golden/lang/test_for_in)
  - add positive interface-typed `for ... in` cases
- [tests/golden/lang/test_virtual_dispatch](../tests/golden/lang/test_virtual_dispatch)
  - add or extend cases proving override-sensitive behavior through interface-typed sugar

## Ordered Implementation Checklist

## Slice 1: Add Interface Structural Dispatch To IR

- [x] add `InterfaceDispatch` to [compiler/semantic/ir.py](../compiler/semantic/ir.py)
- [x] extend `SemanticDispatch` to include it
- [x] update helper functions that inspect dispatch unions

Test:

- [x] add focused IR helper coverage in [tests/compiler/semantic/test_ir.py](../tests/compiler/semantic/test_ir.py) for the new dispatch shape and helper behavior

## Slice 2: Extend Structural Typechecking For Interface Receivers

- [x] update `resolve_for_in_element_type(...)` in [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
- [x] update `resolve_index_expression_type(...)` in [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
- [x] update index-assignment checks in [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
- [x] update slice protocol inference in [compiler/typecheck/structural.py](../compiler/typecheck/structural.py)
- [x] refactor duplicated class-only protocol validation into shared class-or-interface helpers where practical

Test:

- [x] add positive interface-typed protocol tests in [tests/compiler/typecheck/test_structural.py](../tests/compiler/typecheck/test_structural.py)
- [x] add negative interface signature tests in [tests/compiler/typecheck/test_structural.py](../tests/compiler/typecheck/test_structural.py)

## Slice 3: Lower Interface-Typed Structural Sugar To Interface Dispatch

- [ ] update `resolve_collection_dispatch(...)` in [compiler/semantic/lowering/collections.py](../compiler/semantic/lowering/collections.py) to return `InterfaceDispatch` for interface receivers
- [ ] ensure [compiler/semantic/lowering/statements.py](../compiler/semantic/lowering/statements.py) `for ... in` lowering works unchanged once dispatch resolution is updated
- [ ] validate that index, slice, and assignment lowering paths continue using structural nodes with the new dispatch kind

Test:

- [ ] add lowering assertions for interface-typed `[]`, `[:]`, `[]=`, `[:]=`, and `for ... in` in [tests/compiler/semantic/test_lowering.py](../tests/compiler/semantic/test_lowering.py)

## Slice 4: Emit Interface Dispatch For Structural Sugar

- [ ] extend `_emit_dispatch_call(...)` in [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [ ] route structural interface dispatch through the existing interface slot and method slot lookup helpers in [compiler/codegen/emitter_expr.py](../compiler/codegen/emitter_expr.py)
- [ ] validate index reads, slice reads, writes, and loop protocol calls through the generic dispatch path

Test:

- [ ] add codegen unit coverage in [tests/compiler/codegen/test_emitter_expr.py](../tests/compiler/codegen/test_emitter_expr.py)
- [ ] add codegen statement coverage in [tests/compiler/codegen/test_emitter_stmt.py](../tests/compiler/codegen/test_emitter_stmt.py)

## Slice 5: Update Dispatch Analyses And Reachability

- [ ] update rooted-argument analysis in [compiler/codegen/layout.py](../compiler/codegen/layout.py)
- [ ] update dispatch GC-effect analysis in [compiler/codegen/effects.py](../compiler/codegen/effects.py)
- [ ] update reachability handling for structural interface dispatch in [compiler/semantic/optimizations/unreachable_prune.py](../compiler/semantic/optimizations/unreachable_prune.py)

Test:

- [ ] add or update pruning coverage in [tests/compiler/semantic/optimizations/test_unreachable_prune.py](../tests/compiler/semantic/optimizations/test_unreachable_prune.py)
- [ ] run focused codegen and semantic optimization tests covering interface calls and structural sugar

## Slice 6: Add End-To-End Language Coverage

- [ ] add positive golden coverage for interface-typed indexing and slicing in [tests/golden/lang/test_indexing_sugar](../tests/golden/lang/test_indexing_sugar)
- [ ] add positive golden coverage for interface-typed `for ... in` in [tests/golden/lang/test_for_in](../tests/golden/lang/test_for_in)
- [ ] extend override-sensitive language tests in [tests/golden/lang/test_virtual_dispatch](../tests/golden/lang/test_virtual_dispatch) so interface-typed sugar proves correct override behavior

Test:

- [ ] run the relevant golden suites
- [ ] run focused integration coverage if any new end-to-end runtime cases are added outside golden tests

## Validation Checklist

- [x] typecheck unit tests for structural protocols pass
- [x] semantic lowering tests for structural dispatch pass
- [ ] codegen emitter tests for interface dispatch pass
- [ ] semantic optimization tests still pass after reachability updates
- [ ] golden tests for indexing sugar pass
- [ ] golden tests for `for ... in` pass
- [ ] golden tests for virtual/interface dispatch pass
- [x] full targeted pytest selection for touched areas passes

## Non-Goals

This plan does not include:

- changing the surface sugar design
- making arrays implement user-visible interfaces for sugar
- rewriting structural sugar into general method-call AST before semantic lowering
- introducing a new runtime ABI for interface values
- devirtualizing structural interface sugar as part of the initial correctness implementation

## Recommended Implementation Order

Implement this in the order above.

The critical sequencing is:

1. define the new dispatch shape
2. teach typechecking and lowering to produce it
3. teach codegen and reachability to consume it
4. then add end-to-end golden coverage

That order minimizes the chance of partially-wired interface sugar paths producing silent mis-lowering or being accidentally pruned during optimization.