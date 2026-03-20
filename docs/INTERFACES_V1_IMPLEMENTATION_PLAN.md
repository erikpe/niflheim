# Interfaces v1 Implementation Plan

This document describes a concrete implementation plan for interfaces v1.

It is the execution companion to [INTERFACES_V1.md](INTERFACES_V1.md), which defines the design principles, language/runtime decisions, semantic IR shape, and runtime metadata direction for the feature.

Use [INTERFACES_V1.md](INTERFACES_V1.md) as the source of truth for design intent. Use this document to track execution progress.

## Status

In progress.

Completed so far:

- Step 1 is implemented and validated.
- Step 2 is implemented and validated.
- Step 3 is implemented and validated.
- Step 4 is implemented and validated.
- Step 5 is implemented and validated.
- Step 6 is implemented and validated.

Not started yet:

- Step 7 and later.

## Scope

This plan targets the minimal v1 interface feature described in [INTERFACES_V1.md](INTERFACES_V1.md):

- interface declarations with method signatures only
- class `implements` clauses
- compile-time interface conformance checking
- interface types as first-class reference types
- explicit runtime-checked casts to interfaces
- dynamic dispatch through interface-typed receivers

This plan does not include:

- interface inheritance
- default methods
- generic interfaces
- built-in automatic interface implementation for arrays or runtime container types

Locked v1 decisions inherited from [INTERFACES_V1.md](INTERFACES_V1.md):

- interface values use the same raw object-pointer runtime representation as class references and `Obj`
- interfaces are exportable/importable exactly like classes
- private methods do not satisfy interface conformance
- direct explicit interface-to-interface casts are allowed and runtime-checked
- interface method references are out of scope for v1

## Overall Milestones

- frontend understands interface syntax
- typechecker understands interface declarations, imports, and conformance
- semantic IR can represent interface dispatch explicitly
- runtime metadata supports implemented-interface lookup
- codegen can emit interface casts and interface dispatch
- stdlib/integration tests demonstrate the feature end-to-end

## Recommended Order

Implement in this order:

1. frontend syntax and AST
2. symbol identity and declaration inventory
3. typechecker interface model and conformance
4. type relations and cast legality
5. semantic IR node additions
6. semantic lowering of interface calls/casts
7. runtime metadata extension
8. runtime interface cast support
9. codegen metadata emission
10. codegen interface dispatch
11. integration and stdlib adoption

## Step-By-Step Checklist

## Step 1: Add Frontend Syntax And AST Nodes

- [x] Add lexer keyword support for `interface` and `implements`
- [x] Extend parser grammar to parse interface declarations
- [x] Extend parser grammar to parse class `implements` clauses
- [x] Add frontend AST nodes for interfaces
- [x] Extend `ModuleAst` to hold interfaces
- [x] Extend `ClassDecl` to hold implemented interface type refs

Suggested code areas:

- `compiler/frontend/tokens.py`
- `compiler/frontend/parser.py`
- `compiler/frontend/ast_nodes.py`
- parser tests under `tests/compiler/frontend/parser/`

Suggested tests for this step:

- parse a single interface with one method
- parse a class implementing one interface
- parse a class implementing multiple interfaces
- reject invalid interface bodies (for example method body present)
- reject malformed `implements` syntax

What should be achieved at the end of this step:

- the frontend can parse interface declarations and class `implements` clauses
- the AST represents interfaces explicitly
- existing non-interface syntax remains unaffected

Validation for this step:

- Implemented in `compiler/frontend/tokens.py`, `compiler/frontend/parser.py`, and `compiler/frontend/ast_nodes.py`
- Covered by focused lexer/parser tests, including:
	- `test_lex_interface_and_implements_keywords`
	- `test_parse_interface_declarations_and_class_implements`
	- `test_parse_rejects_interface_method_body`
	- `test_parse_rejects_malformed_implements_clause`
- Parser AST golden snapshots were refreshed to reflect the explicit `interfaces` and `implements` fields
- Validation run results:
	- focused frontend and compatibility tests: `108 passed`
	- full suite: `426 passed`

Step 1 objective check:

- fulfilled: interface declarations parse at module scope, including `export interface`
- fulfilled: class `implements` clauses parse into explicit type refs
- fulfilled: AST now represents interface declarations and implemented interfaces explicitly
- fulfilled: legacy syntax remains stable under the full test suite

## Step 2: Add Canonical Interface Symbol IDs And Inventory

- [x] Add `InterfaceId`
- [x] Add `InterfaceMethodId`
- [x] Extend semantic symbol indexing to inventory interfaces and interface methods
- [x] Add module-local interface lookup maps
- [x] Add imported-interface lookup support if inventory layer is the right place for it

Suggested code areas:

- `compiler/semantic/symbols.py`
- tests under `tests/compiler/semantic/`

Suggested tests for this step:

- collect interfaces across multiple modules
- distinguish duplicate leaf interface names across modules
- collect interface methods by canonical ID
- verify local module interface lookup by unqualified name
- verify imported interface lookup follows the same local-first and ambiguity rules as classes

What should be achieved at the end of this step:

- interfaces have canonical post-typecheck identity just like classes/functions/methods
- later passes do not need to use ad hoc string parsing for interface ownership

Validation for this step:

- Implemented in `compiler/semantic/symbols.py`
- Resolver symbol inventory was extended in `compiler/resolver.py` so interfaces participate in exported/imported module symbol visibility just like classes
- Added focused tests covering:
	- canonical interface IDs across modules
	- canonical interface method IDs across modules
	- module-local interface lookup maps
	- imported interface lookup with local-first behavior
	- ambiguous imported interface lookup rejection
	- exported interface symbol visibility in resolver
- Validation run results:
	- focused resolver and semantic symbol tests: `12 passed`
	- full suite: `430 passed`

Step 2 objective check:

- fulfilled: interfaces now have canonical `InterfaceId` identity keyed by module path and leaf name
- fulfilled: interface methods now have canonical `InterfaceMethodId` identity keyed by module path, owning interface, and method name
- fulfilled: the semantic symbol index inventories interfaces and interface methods explicitly
- fulfilled: module-local interface lookup maps are available in the symbol index
- fulfilled: imported interface lookup support was added at the inventory layer with local-first and ambiguity behavior

## Step 3: Add Typecheck Interface Declaration Collection

- [x] Add `InterfaceInfo` to the typecheck model
- [x] Extend typecheck context to track local/imported interfaces
- [x] Collect interface declarations during the declaration pass
- [x] Validate duplicate interface declarations within a module
- [x] Validate duplicate interface method names within the same interface

Suggested code areas:

- `compiler/typecheck/model.py`
- `compiler/typecheck/context.py`
- `compiler/typecheck/declarations.py`
- `compiler/typecheck/module_lookup.py`

Suggested tests for this step:

- duplicate interface declaration rejected
- duplicate interface method rejected
- imported interface visible across modules
- interface declaration collection coexists correctly with class/function declarations

What should be achieved at the end of this step:

- the typechecker can resolve interface declarations as named program entities
- interfaces participate in module/import lookup

Validation for this step:

- Implemented in `compiler/typecheck/model.py`, `compiler/typecheck/context.py`, `compiler/typecheck/declarations.py`, `compiler/typecheck/module_lookup.py`, and `compiler/typecheck/api.py`
- Added focused tests covering:
	- duplicate interface declaration rejection
	- duplicate interface method rejection
	- interface declaration collection alongside classes and functions
	- imported interface visibility across modules at the declaration/module-lookup layer
- `module_lookup.py` was cleaned up to share imported and qualified symbol-resolution helpers instead of duplicating class and interface lookup logic
- Validation run results:
	- focused typecheck declaration/import tests: `41 passed`
	- full suite: `434 passed`

Step 3 objective check:

- fulfilled: `InterfaceInfo` now exists in the typecheck model
- fulfilled: the typecheck context now tracks local and module-wide imported interface inventories
- fulfilled: interface declarations are collected during the declaration pass
- fulfilled: duplicate interface declarations within a module are rejected
- fulfilled: duplicate interface method names within the same interface are rejected
- fulfilled: interfaces now participate in typecheck module/import lookup infrastructure

## Step 4: Add Interface Conformance Checking For Classes

- [x] Add a separate post-declaration conformance validation pass after all module declarations are collected
- [x] Extend class declaration checking to validate `implements` lists
- [x] Require every interface method to be implemented by the class
- [x] Require exact method signature matching in v1
- [x] Reject static/private methods as satisfying interface requirements
- [x] Produce clear diagnostics for missing or mismatched methods

Implementation note for this step:

- imported interface conformance should not be checked inside the existing single `collect_module_declarations(...)` loop
- conformance validation should run only after all module declarations have been collected, so imported interface inventories are available consistently across the program
- this keeps Step 4 scoped to conformance while avoiding premature coupling to Step 5 type-relation work

Suggested code areas:

- `compiler/typecheck/declarations.py`
- `compiler/typecheck/module_lookup.py`
- `compiler/typecheck/api.py`
- possibly `compiler/typecheck/statements.py` only if visibility rules are reused there

Suggested tests for this step:

- missing method rejected
- wrong return type rejected
- wrong parameter type rejected
- extra class methods allowed
- multiple implemented interfaces checked together
- imported interface in `implements` list resolved correctly
- private method cannot satisfy interface requirement
- static method cannot satisfy interface requirement

What should be achieved at the end of this step:

- a class declaring `implements` is guaranteed by the typechecker to satisfy the interface contract

Validation for this step:

- Implemented in `compiler/typecheck/declarations.py` and wired in `compiler/typecheck/api.py`
- Interface conformance is validated in a separate post-declaration pass, `validate_interface_conformance(...)`, after all module declarations are collected
- Signature comparison normalizes owner-module-local class and interface names so imported interface signatures can be checked exactly without prematurely requiring Step 5 general interface-type semantics
- Added focused tests covering:
	- missing method rejection
	- wrong return type rejection
	- wrong parameter type rejection
	- extra methods allowed
	- multiple implemented interfaces checked together
	- imported interface in `implements` resolved correctly
	- private method cannot satisfy interface requirement
	- static method cannot satisfy interface requirement
- Validation run results:
	- focused Step 4 declaration/conformance tests: `20 passed`
	- full suite: `442 passed`

Step 4 objective check:

- fulfilled: conformance validation now runs in a separate post-declaration pass after all module declarations are collected
- fulfilled: class `implements` lists are validated against resolved local or imported interfaces
- fulfilled: every required interface method must be implemented by the class
- fulfilled: v1 exact signature matching is enforced for parameter count, parameter types, and return type
- fulfilled: private and static methods are rejected as interface implementations
- fulfilled: conformance errors are reported with method- and interface-specific diagnostics

## Step 5: Extend TypeInfo And Type Relations For Interface Types

- [x] Add interface kind to `TypeInfo`
- [x] Extend type resolution to resolve interface names in annotations
- [x] Extend assignability rules so implementing classes are assignable to interfaces
- [x] Extend cast legality rules for `Obj -> Interface`
- [x] Extend cast legality rules for direct explicit interface-to-interface casts
- [x] Extend cast legality rules for interface-to-class policy
- [x] Keep callable/primitive rules unchanged
- [x] Decide and document whether interfaces are allowed in extern signatures for v1

Suggested code areas:

- `compiler/typecheck/model.py`
- `compiler/typecheck/type_resolution.py`
- `compiler/typecheck/relations.py`
- `compiler/typecheck/module_lookup.py`

Suggested tests for this step:

- local variable of interface type accepted
- parameter/return type using interface accepted
- class instance assignable to implemented interface
- non-implementing class not assignable to interface
- explicit `Obj -> Interface` cast accepted by typechecker
- explicit `InterfaceA -> InterfaceB` cast accepted by typechecker
- invalid primitive/interface casts rejected
- interface types allowed in locals, fields, params, returns, and arrays if v1 keeps that capability

What should be achieved at the end of this step:

- interface types behave as first-class reference types in the type system

Validation for this step:

- Implemented in `compiler/typecheck/model.py`, `compiler/typecheck/declarations.py`, `compiler/typecheck/type_resolution.py`, `compiler/typecheck/relations.py`, and `compiler/typecheck/module_lookup.py`
- `TypeInfo` now distinguishes interface types explicitly, and interface annotations resolve in local, imported, qualified, and array positions
- Assignability now accepts implementing class values for interface targets, interface values for `Obj`, and `null` for interface-typed slots
- Explicit cast legality now accepts `Obj -> Interface`, direct interface-to-interface casts, and interface-to-class casts while preserving existing primitive and callable restrictions
- v1 extern-signature policy is now locked to reject interface types until the FFI ABI is documented and tested explicitly
- Added focused tests covering:
	- interface types in locals, fields, params, returns, and arrays
	- class-to-interface assignment
	- `Obj -> Interface` casts
	- interface-to-interface and interface-to-class casts
	- invalid primitive/interface cast rejection
	- imported interface annotations and assignability across modules
	- interface rejection in extern signatures
- Validation run results:
	- focused Step 5 typecheck suites: `96 passed`
	- full suite: `449 passed`

Step 5 objective check:

- fulfilled: `TypeInfo` now carries an explicit interface kind alongside existing primitive, reference, callable, and null kinds
- fulfilled: type resolution now resolves interface names in annotations for local, imported, and qualified references
- fulfilled: implementing classes are assignable to interface-typed targets
- fulfilled: explicit `Obj -> Interface`, interface-to-interface, and interface-to-class casts are accepted by the typechecker under the v1 policy
- fulfilled: primitive and callable cast rules remain unchanged
- fulfilled: interface types behave as first-class reference-like types in locals, fields, params, returns, and arrays
- fulfilled: v1 now explicitly rejects interface types in extern signatures pending dedicated FFI ABI documentation and validation

## Step 6: Extend Semantic IR For Interface Dispatch

- [x] Add `InterfaceMethodCallExpr`
- [x] Explicitly reject interface method references in v1 instead of adding a reference node by default
- [x] Extend semantic IR unions and invariants documentation if needed
- [x] Keep concrete class dispatch separate from interface dispatch

Suggested code areas:

- `compiler/semantic/ir.py`
- tests under `tests/compiler/semantic/`
- [INTERFACES_V1.md](INTERFACES_V1.md) if the final node shape differs from the proposal

Suggested tests for this step:

- semantic IR construction accepts the new node shape
- any helper/walker code over semantic expressions stays correct with the new node kind
- interface method references are rejected if the language surface can express them

What should be achieved at the end of this step:

- semantic IR can represent interface dispatch explicitly instead of encoding it as a concrete class-method call

Validation for this step:

- Implemented in `compiler/semantic/ir.py`, `compiler/semantic/lowering.py`, `compiler/typecheck/calls.py`, `compiler/typecheck/expressions.py`, and `compiler/semantic/reachability.py`
- Added `InterfaceMethodCallExpr` to the semantic IR with explicit interface and interface-method identity alongside receiver, args, and result type information
- Interface receiver calls now lower to `InterfaceMethodCallExpr` while concrete class receiver calls continue to lower to `InstanceMethodCallExpr`
- Interface method references are now rejected explicitly during typechecking instead of falling through to class-only member logic
- `lower_program(...)` now builds typecheck contexts with module interface inventories and runs the same interface conformance validation pass as the main typecheck pipeline, avoiding semantic/typecheck drift
- Updated semantic reachability walking so the new expression kind is traversed safely
- Added focused tests covering:
	- local interface receiver calls lowering to `InterfaceMethodCallExpr`
	- imported interface receiver calls using canonical interface IDs
	- interface method reference rejection in typecheck
	- semantic reachability traversal through interface-call receivers
- Validation run results:
	- focused Step 6 typecheck and semantic suites: `33 passed`
	- full suite: `454 passed`

Step 6 objective check:

- fulfilled: semantic IR now includes an explicit `InterfaceMethodCallExpr` node for interface dispatch
- fulfilled: interface method references are rejected explicitly in v1 instead of lowering to a method-reference node
- fulfilled: semantic expression unions and walkers now recognize the new interface-call expression kind
- fulfilled: concrete class dispatch remains represented separately via `InstanceMethodCallExpr`

## Step 7: Lower Interface Calls And Interface-Typed Casts

- [ ] Lower interface receiver method calls to `InterfaceMethodCallExpr`
- [ ] Keep concrete class receiver method calls as `InstanceMethodCallExpr`
- [ ] Ensure interface type names survive where codegen/runtime need them
- [ ] Keep cast lowering explicit for interface targets via `CastExprS`

Suggested code areas:

- `compiler/semantic/lowering.py`
- `compiler/typecheck/calls.py`
- `compiler/typecheck/expressions.py`

Suggested tests for this step:

- call on interface-typed local lowers to `InterfaceMethodCallExpr`
- call on concrete receiver still lowers to `InstanceMethodCallExpr`
- `Obj -> Interface` cast lowers as explicit semantic cast
- imported interface references lower correctly

What should be achieved at the end of this step:

- all interface dispatch semantics are explicit before codegen begins

## Step 8: Extend Runtime Metadata For Interfaces

- [ ] Add interface metadata structs to the runtime headers
- [ ] Add implemented-interface table support to runtime type metadata
- [ ] Define stable interface method slot order
- [ ] Define per-class interface method table shape
- [ ] Lock and document that interface values are raw object pointers, not fat pointers

Suggested code areas:

- `runtime/include/runtime.h`
- possibly ABI/runtime documentation under `docs/`
- codegen metadata emission paths later in the plan

Suggested tests for this step:

- runtime unit tests for metadata layout helpers if such helpers are introduced
- codegen-facing tests later should validate emitted interface metadata records structurally

What should be achieved at the end of this step:

- each concrete runtime type can describe which interfaces it implements and how interface methods should dispatch
- interface-typed values have a fixed runtime representation compatible with existing reference/root handling

## Step 9: Add Runtime Interface Cast Support

- [ ] Extend `rt_checked_cast` to understand interfaces, or add a dedicated interface-cast helper
- [ ] Define null-cast behavior for interfaces
- [ ] Define bad-cast diagnostics for interface failures

Suggested code areas:

- `runtime/src/runtime.c`
- `runtime/include/runtime.h`
- runtime tests under `tests/runtime/` if appropriate

Suggested tests for this step:

- cast `null` to interface returns `null`
- cast implementing object to interface succeeds
- cast non-implementing object to interface fails with runtime panic
- cast from interface value to another interface is checked at runtime

What should be achieved at the end of this step:

- interface casts are no longer just typechecker rules; the runtime enforces them correctly

## Step 10: Emit Interface Metadata In Codegen

- [ ] Emit interface descriptors
- [ ] Emit per-class implemented-interface records
- [ ] Emit interface method tables in stable slot order
- [ ] Ensure concrete class type metadata continues to work unchanged for existing casts

Suggested code areas:

- `compiler/codegen/emitter_module.py`
- `compiler/codegen/program_generator.py`
- `compiler/codegen/symbols.py`

Suggested tests for this step:

- emitted assembly contains interface metadata records
- emitted assembly contains interface method tables for implementing classes
- existing class type metadata tests still pass unchanged
- interface cast target metadata is emitted for interface targets just as class cast target metadata is emitted for class targets

What should be achieved at the end of this step:

- generated binaries contain enough metadata for interface casts and dispatch to work at runtime

## Step 11: Emit Interface Dispatch Calls

- [ ] Add codegen support for `InterfaceMethodCallExpr`
- [ ] Decide whether dispatch lookup is emitted inline or via a runtime helper
- [ ] If a runtime helper is used, lock its ABI and responsibility split relative to checked-cast logic
- [ ] Preserve current calling convention and root-handling behavior
- [ ] Ensure receiver is passed correctly as the first argument

Suggested code areas:

- `compiler/codegen/emitter_expr.py`
- runtime helper implementation if a helper such as `rt_lookup_interface_method` is used

Suggested tests for this step:

- interface method call emits lookup + indirect call sequence
- integer and reference return paths both work
- interface dispatch preserves argument ordering and receiver passing
- runtime safepoint/root handling remains correct around interface calls
- interface dispatch lookup uses slot-based method table order, not method-name lookup

What should be achieved at the end of this step:

- interface-typed receiver calls work end-to-end in generated code

## Step 12: Add End-To-End Language And Stdlib Coverage

- [ ] Add parser/typecheck/lowering/codegen integration tests for interfaces
- [ ] Add a runtime smoke test for successful interface dispatch
- [ ] Add a runtime failure test for invalid interface cast
- [ ] Add at least one motivating stdlib/integration example, such as `Map` using `Hashable` and `Comparable`

Suggested code areas:

- `tests/compiler/integration/`
- `tests/golden/`
- `std/` if stdlib adoption is included in the same milestone

Suggested tests for this step:

- class implementing one interface works end-to-end
- class implementing two interfaces works end-to-end
- interface cast failure panics at runtime
- interface-based `Map` key path works in golden/integration coverage
- imported interface use across modules works end-to-end
- interface-typed fields/arrays/returns work end-to-end if v1 keeps those capabilities

## Step 13: Update Reachability And Codegen Walkers/Collectors

- [ ] Update semantic reachability for interface dispatch edges if interface dispatch introduces new semantic node kinds that carry interface or method identity
- [ ] Update codegen walkers/collectors to recognize `InterfaceMethodCallExpr`
- [ ] Update any metadata collectors that inspect cast targets or expression kinds

Suggested code areas:

- `compiler/semantic/reachability.py`
- `compiler/codegen/walk.py`
- `compiler/codegen/emitter_module.py`
- `compiler/codegen/strings.py` if relevant expression-kind switches are extended there

Suggested tests for this step:

- reachability keeps interface-dispatch-dependent declarations alive if needed by the final design
- codegen collectors continue to traverse all relevant expressions after adding interface call nodes
- existing walker-based codegen helpers remain correct with the new expression kind

What should be achieved at the end of this step:

- auxiliary semantic/codegen passes remain aligned with the expanded semantic IR

What should be achieved at the end of this step:

- the feature is proven across all layers, not just locally in parser/typecheck/codegen

## Final Validation Checklist

- [ ] `pytest -q`
- [ ] golden tests if interface examples are added there
- [ ] runtime harness/smoke validation for interface cast/dispatch helpers
- [ ] docs updated if the feature becomes active rather than planned

## Review Checklist

Before considering interfaces v1 complete, verify all of the following:

- [ ] interfaces are represented explicitly in the frontend, typechecker, semantic IR, runtime metadata, and codegen
- [ ] classes cannot claim interface conformance without exact method coverage
- [ ] `Obj -> Interface` casts are runtime-checked, not compile-time-only assumptions
- [ ] interface dispatch does not reuse concrete-method call nodes incorrectly
- [ ] interface values use the same raw object-pointer runtime representation everywhere
- [ ] existing class-cast and class-method behavior remains stable
- [ ] at least one real motivating use case is covered end-to-end

## Out-Of-Scope Follow-Ups

Once v1 is stable, possible follow-up work includes:

- interface inheritance
- default methods
- built-in/runtime types implementing interfaces
- generic containers constrained by interface types
- interface-to-interface optimization and cached dispatch