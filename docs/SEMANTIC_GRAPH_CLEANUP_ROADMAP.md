# Semantic Graph Cleanup Roadmap

This document defines the follow-on cleanup plan after the semantic graph identity refactor.

The identity roadmap solved the biggest correctness problem: local binding identity no longer depends on source spelling. The remaining work is more structural. The semantic graph still mixes canonical semantic data with cached display data, still carries some typed-AST-era node shapes, and still lets a few backend-oriented details leak into the main semantic representation.

This roadmap describes how to clean that up in dependency order without destabilizing the compiler.

## Relationship To Existing Documents

- [SEMANTIC_IR_SPEC.md](SEMANTIC_IR_SPEC.md) describes the current implemented semantic IR shape.
- [SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md](SEMANTIC_GRAPH_IDENTITY_REFACTOR_ROADMAP.md) describes the completed identity migration.
- This document covers the next layer of cleanup: making the graph more canonical, less duplicated, and less syntax-shaped.

## Why This Refactor Exists

The current semantic graph is now correct about symbol identity, but several parts still look transitional:

- many nodes still carry both `SemanticTypeRef` and string type fields
- local use-site nodes still copy readability metadata that now lives authoritatively in owner-local tables
- several expression nodes are still shaped like a typed AST rather than a normalized semantic graph
- `SyntheticExpr` is still a generic escape hatch for semantics that are not yet modeled explicitly
- the current graph mixes source-near semantic structure with execution-shaped lowered details such as `SemanticForIn` helper locals

None of these are urgent correctness bugs. They are design and maintenance costs.

## Goals

- make one representation authoritative for semantic type identity
- reduce duplicated metadata on semantic use-site nodes
- separate semantic meaning from source-token spelling where practical
- make synthetic or backend-facing semantics explicit instead of generic
- define a cleaner boundary between source-level semantic IR and lowered semantic IR
- keep diagnostics and debugging readable throughout the migration

## Non-Goals

- do not introduce SSA in this roadmap
- do not replace the structured semantic graph with CFG or bytecode IR
- do not redesign the language surface
- do not combine this with unrelated runtime or backend feature work
- do not force codegen onto a radically different IR shape in a single step

## Design Principles

1. One fact should have one owner.
   If a type, local display name, or dispatch target is canonical somewhere, other copies should become derived or temporary compatibility views.

2. Semantic nodes should describe resolved meaning, not just typed syntax.
   Operator strings, generic synthetic nodes, and syntax-shaped variants should gradually give way to semantically resolved forms.

3. High-level semantic structure and low-level lowering structure should be distinct when they serve different purposes.
   If a node exists only because codegen needs it, that detail should not be forced into the source-near semantic layer forever.

4. Diagnostics remain a first-class constraint.
   Removing cached names or strings must not make errors, debug dumps, or tests unreadable.

## Current Baseline

Today the semantic graph has these notable properties:

- global declarations and local bindings use canonical IDs
- owner-local metadata is authoritative for local names, declared types, declaration spans, and binding kinds
- many semantic nodes still store both `SemanticTypeRef` and `type_name`-style string data
- `LocalRefExpr`, `LocalLValue`, and some declaration nodes still carry copied display and type metadata for readability and compatibility
- expression nodes such as `UnaryExprS` and `BinaryExprS` still encode semantics partly through source-like operator strings
- call and member-access modeling is explicit but somewhat fragmented across several node kinds with overlapping fields
- `SyntheticExpr` still represents a generic bucket of synthetic semantics
- `SemanticForIn` is now identity-correct, but it still bundles execution-shaped helper locals into the main semantic IR

## Dependency Order

The order below is deliberate.

- canonical type authority should come first because it simplifies every later semantic cleanup
- once type ownership is clear, copied local use-site metadata becomes easier to remove cleanly
- semantic operation and dispatch normalization should happen before splitting semantic layers, otherwise the split just preserves old duplication in two places
- the high-level versus lowered semantic IR boundary should be addressed after the graph is more canonical internally, not before

## Ordered Checklist

1. Make `SemanticTypeRef` the only authoritative semantic type representation
  - [x] define which current `*_type_name` fields remain true compatibility views and which should be removed entirely
  - [x] add helper APIs for display rendering and simple predicates so semantic consumers do not need raw type-name strings
  - [x] migrate semantic passes that still reinterpret type strings to use canonical type refs first
  - [x] restrict `best_effort_semantic_type_ref_from_name(...)` to tests, compatibility shims, or carefully named boundary code
  - Purpose:
    remove the largest remaining source of duplicated semantic truth
  - Expected outcome:
    semantic meaning of types is no longer carried primarily by strings after lowering
  - Tests to add:
    - semantic type traversal tests covering nominal, array, callable, and null forms
    - regression tests proving semantic passes behave the same when display strings change

Step 1 implementation slices:

1.1 Audit and classify current type-string fields
  - [x] inventory every `type_name`, `target_type_name`, `receiver_type_name`, `element_type_name`, and `value_type_name` field in semantic IR
  - [x] classify each field as one of:
    - canonical semantic input still used incorrectly
    - cached display data worth keeping temporarily
    - redundant field that should be removed
  - [x] document which semantic passes and backend paths still read each class of field
  - Stop condition:
    there is a written field-by-field migration table, so later changes do not guess which strings are still required

Step 1.1 audit results:

This table records the current field families, their canonical twin when one exists, their current classification, and the main production readers that still depend on them.

| Field family | Representative semantic IR fields | Canonical twin today | Classification | Main current readers | Notes |
| --- | --- | --- | --- | --- | --- |
| Declaration and signature type strings | `SemanticField.type_name`, `SemanticParam.type_name`, `SemanticInterfaceMethod.return_type_name`, `SemanticFunction.return_type_name`, `SemanticMethod.return_type_name` | `type_ref` or `return_type_ref` on the same node | cached display data worth keeping temporarily | backend emission and layout in `compiler/codegen/emitter_fn.py`, `compiler/codegen/layout.py`, `compiler/codegen/generator.py`; metadata building in `compiler/codegen/metadata.py`; entrypoint validation in `compiler/semantic/linker.py` | These fields still feed ABI, layout, and entrypoint checks. They should remain until codegen and linker can consume canonical refs directly. |
| Owner-local declared type metadata | `SemanticLocalInfo.type_name` | `SemanticLocalInfo.type_ref` | cached display data worth keeping temporarily | layout and parameter spilling in `compiler/codegen/layout.py` and `compiler/codegen/emitter_fn.py`; owner-local helper builders in `compiler/semantic/ir.py` | This is now the authoritative readable local-type cache, so it is not a near-term removal target even though the canonical twin exists. |
| Local declaration compatibility field | `SemanticVarDecl.type_name` | owner-local metadata via `local_info_by_id[local_id].type_ref` and `type_name` | redundant field that should be removed | no current production readers; only tests explicitly assert that it is absent | This field is already effectively dead in production after the identity migration. It is the clearest early removal candidate once the docs and tests are aligned. |
| Local use-site result type strings | `LocalRefExpr.type_name`, `LocalLValue.type_name` | `type_ref` on the same node plus owner-local metadata | canonical semantic input still used incorrectly | semantic folding in `compiler/semantic/optimizations/constant_folding.py`; generic expression typing through `compiler/semantic/ir.py:expression_type_name`; broad backend use through `compiler/codegen/emitter_expr.py` and `compiler/codegen/layout.py` | These nodes already carry canonical refs, so semantic and backend consumers reading the string are compatibility-era behavior, not a modeling requirement. |
| Receiver and target compatibility strings | `FieldReadExpr.receiver_type_name`, `FieldLValue.receiver_type_name`, `InstanceMethodCallExpr.receiver_type_name`, `InterfaceMethodCallExpr.receiver_type_name`, `CastExprS.target_type_name`, `TypeTestExprS.target_type_name` | `receiver_type_ref` or `target_type_ref` on the same node | canonical semantic input still used incorrectly | constant folding on casts in `compiler/semantic/optimizations/constant_folding.py`; lowering compatibility helpers in `compiler/semantic/lowering/ids.py`; runtime type metadata and cast emission in `compiler/codegen/emitter_expr.py` and `compiler/codegen/metadata.py` | These fields are the main example of semantics still branching on string type names even when a canonical ref already exists. |
| Collection element and value compatibility strings | `SemanticForIn.element_type_name`, `ArrayCtorExprS.element_type_name`, `IndexLValue.value_type_name`, `SliceLValue.value_type_name` | `element_type_ref` or `value_type_ref` on the same node | canonical semantic input still used incorrectly | array dispatch selection in `compiler/semantic/lowering/collections.py`; `for-in` iteration emission in `compiler/codegen/emitter_stmt.py`; array constructor emission in `compiler/codegen/emitter_expr.py` | These strings still drive runtime-kind selection. That logic should eventually move to canonical type helpers rather than direct string matching. |
| General expression result type strings on nodes that already have a canonical ref | `FieldReadExpr.type_name`, `FieldLValue.type_name`, `IndexLValue.value_type_name`, `SliceLValue.value_type_name`, `FunctionRefExpr.type_name`, `ClassRefExpr.type_name`, `MethodRefExpr.type_name` | `type_ref` or `value_type_ref` on the same node | canonical semantic input still used incorrectly | constant folding and generic expression helpers; backend expression emission and layout planning | These are strong candidates for migration once helper APIs exist, because the canonical result type is already attached to the node. |
| General expression result type strings on nodes that do not yet carry a canonical result-type ref | `LiteralExprS.type_name`, `UnaryExprS.type_name`, `BinaryExprS.type_name`, `FunctionCallExpr.type_name`, `StaticMethodCallExpr.type_name`, `InstanceMethodCallExpr.type_name`, `InterfaceMethodCallExpr.type_name`, `ConstructorCallExpr.type_name`, `CallableValueCallExpr.type_name`, `IndexReadExpr.type_name`, `SliceReadExpr.type_name`, `ArrayCtorExprS.type_name`, `SyntheticExpr.type_name` | no direct node-local canonical result type field yet | cached display data worth keeping temporarily | constant folding, `expression_type_name(...)`, and much of `compiler/codegen/emitter_expr.py` | These fields are still carrying real semantic information because the corresponding node-local canonical result type has not been modeled yet. They should not be removed before step `1.4` tightens type ownership at IR construction time. |
| Hard-coded compatibility default result strings | `NullExprS.type_name`, `ArrayLenExpr.type_name` | implicit semantic type (`null` and `u64`) | cached display data worth keeping temporarily | generic expression helpers and backend emission paths | These are low-risk fields but not worth changing before the broader result-type story is clearer. |

Current reader summary by subsystem:

- Semantic passes already mostly prefer canonical refs for graph traversal. Reachability in `compiler/semantic/optimizations/reachability.py` uses `SemanticTypeRef` wherever it is available and falls back to string parsing only for node families that still lack canonical result refs.
- Semantic optimizations still use string types directly for executable behavior. Constant folding in `compiler/semantic/optimizations/constant_folding.py` compares and branches on `expr.type_name` and `expr.target_type_name` today.
- Lowering-time collection and dispatch helpers still select array runtime kinds and nominal dispatch paths from strings in `compiler/semantic/lowering/collections.py` and `compiler/semantic/lowering/ids.py`.
- Backend codegen remains heavily string-driven. The main readers are `compiler/codegen/emitter_expr.py`, `compiler/codegen/emitter_stmt.py`, `compiler/codegen/layout.py`, `compiler/codegen/emitter_fn.py`, and `compiler/codegen/metadata.py`.
- `best_effort_semantic_type_ref_from_name(...)` is already confined to tests and compatibility reconstruction inside `compiler/semantic/types.py`; there are no current production call sites outside that module.

Conclusion of step 1.1:

- The immediate high-value migration targets are the field families already carrying canonical refs: local use-site result strings, receiver and target compatibility strings, and collection element/value compatibility strings.
- The immediate removal target is `SemanticVarDecl.type_name`, because it no longer has production readers.
- Declaration/signature strings and general expression result `type_name` fields should remain temporary compatibility data until later slices give those consumers a canonical alternative.

Step 1.1 status:

- complete
- no executable tests added; this slice is a documentation and audit step, and its validation is the migration table itself

1.2 Establish canonical type helper APIs
  - [x] add central helper APIs for common semantic questions now answered via string inspection
  - [x] cover at least:
    - nominal identity
    - primitive/reference/interface/array/callable/null kind checks
    - array element access
    - callable parameter and return access
    - rendering a stable display string from `SemanticTypeRef`
  - [x] move string-parsing helpers behind explicitly compatibility-named boundaries
  - Stop condition:
    new semantic code can ask normal type questions without branching on raw type-name strings

Step 1.2 status:

- complete
- `compiler/semantic/types.py` now exposes canonical helper APIs for type kind checks, nominal identity, array element access, callable parameter access, callable return access, display-name rendering, and canonical-name rendering.
- raw string reconstruction now has an explicit compatibility entrypoint via `compat_semantic_type_ref_from_name(...)`.
- the older `best_effort_semantic_type_ref_from_name(...)` name remains as a thin compatibility wrapper for now; fencing off remaining direct uses is still tracked separately in step `1.5`.

1.3 Migrate semantic analyses to canonical type refs first
  - [x] update semantic passes that currently reinterpret strings, starting with reachability and any semantic helpers that still parse nominal names or callable signatures
  - [x] make migrated passes treat type strings as fallback-only compatibility data rather than primary input
  - [x] keep the migration narrow enough that codegen is not forced to switch in the same step
  - Stop condition:
    semantic analyses no longer need string parsing for the node categories already carrying canonical type refs

Step 1.3 status:

- complete
- semantic reachability no longer maintains its own local parser for callable and nominal type strings.
- `compiler/semantic/optimizations/reachability.py` now follows canonical `SemanticTypeRef` structure through shared helper APIs and uses type-name reconstruction only as an explicit compatibility fallback.
- this step intentionally does not migrate codegen or constant-folding result-type logic yet; those consumers still rely on string fields that remain compatibility or executable data until later slices.

1.4 Tighten type ownership at the IR construction boundary
  - [x] make lowering populate canonical `SemanticTypeRef` values for any remaining frequently used nodes that still rely mainly on strings
  - [x] reduce creation of semantic nodes that have meaningful type strings but missing canonical type refs
  - [x] treat missing canonical type info as a bug in lowering unless the node is explicitly marked as a compatibility case
  - Stop condition:
    newly lowered semantic nodes consistently arrive with canonical type refs wherever later semantic passes need them

Step 1.4 status:

- complete
- lowering now populates canonical result `type_ref` values for the main executable expression families that previously carried only `type_name`, including literals, unary and binary expressions, casts, type tests, call nodes, array reads and slices, array constructors, and synthetic string-literal byte payloads.
- `NullExprS` and `ArrayLenExpr` now expose built-in canonical type refs for their fixed result types, so executable semantic expressions have a uniform canonical type query even when the result type is intrinsic rather than inferred from typecheck output.
- the remaining string result fields are now explicitly compatibility and display data for these node families rather than the only semantic type payload established at lowering time.

1.5 Fence off `best_effort_semantic_type_ref_from_name(...)`
  - [x] move direct production usage behind carefully named compatibility helpers or clearly delimited boundary modules
  - [x] keep direct use in tests where synthetic semantic fixtures are still handwritten
  - [x] add comments or assertions clarifying that the function is a reconstruction shim, not the preferred semantic path
  - Stop condition:
    the codebase makes it visually obvious which type refs are canonical lowering output and which are reconstructed compatibility values

Step 1.5 status:

- complete
- direct `best_effort_semantic_type_ref_from_name(...)` usage is now confined to handwritten test fixtures; production reconstruction sites use the explicitly named `compat_semantic_type_ref_from_name(...)` boundary instead.
- `compiler/semantic/types.py` now documents the distinction directly: `compat_...` is the production compatibility shim, while `best_effort_...` is retained as a backward-compatible convenience wrapper for tests.
- semantic type tests pin the wrapper behavior so future cleanup can remove or rename it deliberately instead of letting production call sites drift back in implicitly.

1.6 Remove the first redundant string fields
  - [x] pick a small set of high-confidence redundant fields and remove them after their consumers have switched to canonical refs
  - [x] prefer fields on nodes already carrying an equivalent `SemanticTypeRef` and already consumed semantically through that ref
  - [x] keep display rendering centralized so diagnostics do not regress when the copied string disappears
  - Stop condition:
    at least one end-to-end slice proves a semantic node family can operate without duplicated type strings

Step 1.6 status:

- `SemanticVarDecl.type_name` has been removed. It had no remaining production readers and was already effectively dead compatibility data after the local-metadata migration.
- `FunctionRefExpr.type_name`, `ClassRefExpr.type_name`, and `MethodRefExpr.type_name` have also been removed. These nodes already carried equivalent canonical `type_ref` values, and no production reader required the copied string once `expression_type_name(...)` was taught to render reference-expression display names from the canonical ref.
- this slice keeps compatibility rendering centralized in `compiler/semantic/ir.py:expression_type_name(...)`, so downstream code that still asks for a display-oriented type name does not need to know which nodes still store a copied string and which derive one from canonical metadata.

1.7 Re-evaluate remaining string type fields after the first migration slice
  - [ ] update the migration table from step 1.1 with what is now truly required for compatibility
  - [ ] decide which remaining fields are acceptable long-lived caches and which belong in later removal slices
  - [ ] only then move to step 2 of the cleanup roadmap
  - Stop condition:
    step 1 ends with a narrowed, explicit, justified set of remaining type-string compatibility fields rather than a blanket duplication policy

2. Remove copied local readability and declared-type data from local use sites
  - [ ] stop treating `LocalRefExpr.name`, `LocalRefExpr.type_name`, `LocalLValue.name`, and similar fields as semantic data
  - [ ] decide whether those fields should be removed outright or retained only in debug-only wrappers/builders
  - [ ] update diagnostics and codegen helpers to recover display metadata strictly through owner-local lookup APIs
  - [ ] finish the same cleanup for `SemanticVarDecl` compatibility fields if any remaining downstream users still depend on them
  - Purpose:
    make `LocalId` plus owner metadata the only semantic local source of truth
  - Expected outcome:
    local use-site nodes describe identity and value flow, not cached copies of declaration metadata
  - Tests to add:
    - diagnostics tests proving local names still appear correctly after copied name removal
    - codegen and optimization tests using synthetic or rewritten semantic functions with owner metadata only

3. Normalize semantic operations away from raw source-token strings
  - [ ] introduce canonical enums or operation descriptors for unary, binary, cast, and type-test semantics where raw strings still do semantic work
  - [ ] distinguish operations whose source spelling matches but whose semantics differ after type resolution
  - [ ] keep pretty-printing helpers so test output and diagnostics stay readable
  - Purpose:
    move the graph from typed syntax toward resolved semantic operations
  - Expected outcome:
    later passes ask semantic questions directly instead of branching on source token text
  - Tests to add:
    - constant-folding and codegen tests keyed by semantic op kind rather than operator string spelling
    - regression tests for operations whose legality depends on resolved operand type

4. Normalize resolved call and member-access modeling
  - [ ] factor the overlapping call/member fields into a clearer resolved target model
  - [ ] decide whether instance, static, interface, constructor, and callable-value invocation should remain separate node kinds or share a common resolved call payload
  - [ ] define a canonical dispatch structure that owns receiver type, target identity, and dispatch mode
  - Purpose:
    reduce duplicated call-shape logic and make dispatch reasoning easier across semantic passes and codegen
  - Expected outcome:
    call semantics live in one consistent model instead of several partially overlapping node forms
  - Tests to add:
    - semantic lowering tests covering every resolved call category through the same normalization boundary
    - codegen tests proving normalized call metadata still produces correct labels and runtime dispatch

5. Replace `SyntheticExpr` with explicit semantic node kinds or explicit synthetic categories
  - [ ] inventory all current `SyntheticExpr` uses and group them by actual semantic meaning
  - [ ] promote common synthetic forms into dedicated node types where semantics are stable
  - [ ] if any generic synthetic bucket remains, make it a narrowly typed, well-documented escape hatch rather than an open-ended catch-all
  - Purpose:
    prevent the semantic graph from accumulating an unstructured miscellaneous node
  - Expected outcome:
    synthetic semantics become visible and reviewable in the node set itself
  - Tests to add:
    - semantic walk and reachability tests covering the new explicit synthetic node coverage
    - regression tests proving no old synthetic use falls through undocumented paths

6. Define an explicit split between source-level semantic IR and lowered semantic IR
  - [ ] decide whether the compiler should keep one IR with phases or two closely related IR layers
  - [ ] identify which current nodes belong naturally to source-level semantics versus lowered execution-oriented semantics
  - [ ] move execution-shaped details such as `SemanticForIn` helper-local bookkeeping behind a lowered-semantic boundary if that split pays for itself
  - [ ] keep high-level semantic analyses operating on the source-near layer wherever practical
  - Purpose:
    stop one semantic graph from serving two different abstraction levels indefinitely
  - Expected outcome:
    source reasoning stays readable while codegen and backend preparation can still consume an explicit lowered form
  - Tests to add:
    - boundary tests proving source-level analysis output lowers deterministically into the execution-oriented layer
    - codegen regressions proving lowered helper locals remain explicit and identity-correct after the split

7. Audit diagnostics, walkers, and tests for over-coupling to compatibility fields
  - [ ] remove tests that assert transitional storage details instead of semantic invariants
  - [ ] centralize display rendering helpers for types, locals, and resolved call targets
  - [ ] ensure semantic walkers and future optimization scaffolding rely on canonical fields only
  - Purpose:
    make the previous cleanup steps durable instead of reintroducing compatibility dependencies through tests and tooling
  - Expected outcome:
    the semantic graph stays canonical because the surrounding tooling no longer depends on transitional node copies
  - Tests to add:
    - walk and debug-format tests that validate central rendering helpers instead of node-field duplication

## Recommended Execution Slices

If this roadmap is implemented incrementally, use these slices:

1. canonical-type authority
2. local use-site metadata removal
3. operation normalization
4. call and dispatch normalization
5. synthetic-node cleanup
6. semantic-layer split
7. tooling and test audit

## Success Criteria

This roadmap is complete when all of the following are true:

- semantic passes can use canonical type identity without reinterpreting type-name strings
- local use-site nodes no longer own semantic copies of declaration metadata
- operator and dispatch semantics are represented canonically rather than by token text and ad hoc field duplication
- generic synthetic semantics are either explicit node kinds or a narrowly constrained documented escape hatch
- the boundary between source-level semantic reasoning and lowered execution-oriented structure is explicit
- diagnostics and debug output remain readable through central rendering helpers rather than semantic duplication