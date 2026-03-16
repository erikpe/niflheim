# Typecheck Refactor Plan

This document describes a concrete plan to split the typechecker into smaller modules with clear responsibilities while preserving current behavior.

The immediate goal is readability and maintainability. The medium-term goal is to make future type-system work, such as richer reference relationships, protocol-like structural checks, or more type forms, cheaper to add without re-growing a single monolithic checker file.

## Goals

- Keep the public API stable through the `compiler.typecheck` import path.
- Separate semantic concerns from traversal/state management.
- Move reusable type logic into small, testable helpers.
- Make cross-module lookup and member-qualification rules explicit.
- Preserve current diagnostics and semantics during the refactor.
- Create seams where future type-system features can be added without touching every checker branch.

## Non-Goals

- Do not change language semantics as part of this refactor.
- Do not redesign the entire semantic model up front.
- Do not mix the refactor with unrelated type-rule improvements.
- Do not replace the existing test suite structure before the implementation split is stable.

## Current Problems

The current implementation in `compiler/typecheck_checker.py` mixes several distinct responsibilities in one large stateful class:

- declaration collection and symbol pre-pass
- scope and loop-state management
- type-reference resolution
- module/import lookup
- expression inference
- call checking
- structural indexing/slicing protocols
- assignment and cast relations
- control-flow and return-path checking
- privacy/visibility enforcement

This makes the file difficult to navigate and increases coupling between unrelated concepts. It also makes future type-system changes harder because core helpers are spread across large `if` ladders instead of being owned by focused modules.

## Refactor Principles

## 1. Keep One Public Entry Point

The `compiler.typecheck` import path should remain the stable public facade for:

- `typecheck(module_ast)`
- `typecheck_program(program)`

Internal structure may change, but callers should not need to know about the refactor.

## 2. Prefer Explicit Context Over Giant Methods

Most checker operations should become functions that accept an explicit context object instead of methods hanging off one monolithic class.

Preferred shape:

- `infer_expr_type(ctx, expr)`
- `check_statement(ctx, stmt, return_type)`
- `resolve_type_ref(ctx, type_ref)`
- `require_assignable(ctx, target, value, span)`

This makes dependencies visible, reduces accidental coupling, and improves testability.

## 3. Separate Policy From Traversal

Type relations such as equality, assignability, comparability, and explicit-cast validity should not be embedded in statement or expression traversal code. They should live in dedicated helpers.

## 4. Keep Data Model Stable First

`TypeInfo`, `FunctionSig`, and `ClassInfo` can remain structurally similar during the first refactor. The first pass should improve module boundaries, not redesign the semantic model.

## 5. Extract Pure Helpers Early

Pure helpers and lookup logic should move first because they are low-risk and unlock the later splits.

## 6. Move Structural Protocol Rules Behind Named Helpers

The current checker already has implicit protocols for:

- array indexing and slicing
- user-defined `index_get` and `index_set`
- user-defined `slice_get` and `slice_set`
- `for in` iteration through `iter_len` and `iter_get`

These should be grouped into one place instead of remaining spread across expression and statement checking.

## 7. Preserve Diagnostics While Refactoring

Existing error wording and span behavior should remain stable as much as practical so the current tests continue to protect behavior.

## Target Layout

The recommended end state is a small `compiler/typecheck/` package whose `__init__.py` acts as the public facade.

Suggested layout:

```text
compiler/
  typecheck/
    __init__.py                  # stable public facade for compiler.typecheck imports
    api.py                       # public orchestration helpers used by facade
    model.py                     # TypeInfo, FunctionSig, ClassInfo, TypeCheckError, constants
    context.py                   # mutable checking context and scope helpers
    constants.py                 # operator sets, literal bounds, array member names
    declarations.py              # declaration pre-collection and signature construction
    type_resolution.py           # resolve TypeRefNode -> TypeInfo and owner qualification
    module_lookup.py             # import/module/class/function lookup helpers
    relations.py                 # equality, assignability, comparability, casts, display helpers
    structural.py                # indexing, slicing, iterability protocol validation
    expressions.py               # non-call expression inference
    calls.py                     # all call inference and call-argument checking
    statements.py                # blocks, statements, control flow, return analysis
```

## File Purposes

## `compiler/typecheck/__init__.py`

Purpose:

- Preserve the existing external API.
- Import the real implementation from `compiler.typecheck.api`.
- Keep all downstream imports stable during and after the refactor.

Expected size:

- very small

## `compiler/typecheck/api.py`

Purpose:

- Implement `typecheck` and `typecheck_program`.
- Own the two-pass program workflow.
- Construct per-module contexts and pass shared declaration tables into phase 2.

This module should not contain expression or statement rules.

## `compiler/typecheck/model.py`

Purpose:

- Hold `TypeInfo`, `FunctionSig`, `ClassInfo`, and `TypeCheckError`.
- Hold model-level constants that define basic type categories.

Candidate contents:

- `PRIMITIVE_TYPE_NAMES`
- `REFERENCE_BUILTIN_TYPE_NAMES`
- `NUMERIC_TYPE_NAMES`

Future extension point:

- This is the natural place to later evolve `TypeInfo` into a richer tagged semantic type model.

## `compiler/typecheck/context.py`

Purpose:

- Hold mutable per-check state in one explicit object.
- Replace hidden checker instance state with named fields.

Recommended contents:

- module AST reference
- current module path
- all modules/program tables
- collected local module function signatures
- collected local module class infos
- scope stack
- function-local name tracking
- loop depth
- current private-owner marker

Recommended API shape:

- `push_scope(ctx)`
- `pop_scope(ctx)`
- `declare_variable(ctx, name, type_info, span)`
- `lookup_variable(ctx, name)`

## `compiler/typecheck/constants.py`

Purpose:

- Move operational constants out of the semantic engine.

Candidate contents:

- `ARRAY_METHOD_NAMES`
- literal bounds for `i64` and `u64`
- bitwise operator type sets

## `compiler/typecheck/declarations.py`

Purpose:

- Own the declaration pre-pass.
- Collect classes, fields, methods, and top-level functions.
- Validate duplicate declarations and field initializer restrictions.

Recommended functions:

- `collect_module_declarations(ctx)`
- `function_sig_from_decl(ctx, decl)`
- `check_constant_field_initializer(expr)`

This module should not do full statement or expression checking except the limited constant-expression validation already needed for field initializers.

## `compiler/typecheck/type_resolution.py`

Purpose:

- Convert AST type references into semantic `TypeInfo` values.
- Resolve imported and qualified class types.
- Qualify member types relative to owning module/class.
- Resolve the built-in string type without depending on unrelated checker branches.

Recommended functions:

- `resolve_type_ref(ctx, type_ref)`
- `resolve_string_type(ctx, span)`
- `qualify_member_type_for_owner(ctx, member_type, owner_type_name)`

Future extension point:

- Generic type argument resolution would naturally plug in here later.

## `compiler/typecheck/module_lookup.py`

Purpose:

- Centralize cross-module lookup behavior.
- Remove import-resolution duplication from expression and call inference.

Recommended functions:

- `current_module_info(ctx)`
- `lookup_class_by_type_name(ctx, type_name)`
- `resolve_imported_function_sig(ctx, fn_name, span)`
- `resolve_imported_class_type(ctx, class_name, span)`
- `resolve_qualified_imported_class_type(ctx, qualified_name, span)`
- `resolve_module_member(ctx, expr)`
- `flatten_field_chain(expr)`

## `compiler/typecheck/relations.py`

Purpose:

- Centralize type relations and validation policies.

Recommended functions:

- `canonicalize_reference_type_name(ctx, type_name)`
- `type_names_equal(ctx, left, right)`
- `type_infos_equal(ctx, left, right)`
- `require_assignable(ctx, target, value, span)`
- `is_comparable(ctx, left, right)`
- `check_explicit_cast(ctx, source, target, span)`
- `require_type_name(actual, expected_name, span)`
- `require_array_size_type(actual, span)`
- `require_array_index_type(actual, span)`
- `display_type_name(type_info)`

Future extension point:

- Subtyping, variance, interfaces, or protocol conformance should be added here rather than threaded through every checker branch.

## `compiler/typecheck/structural.py`

Purpose:

- Own protocol-like rules for arrays and user-defined structural members.
- Make indexing, slicing, and iteration semantics discoverable in one place.

Recommended functions:

- `resolve_for_in_element_type(ctx, collection_type, span)`
- `resolve_structural_get_method_result_type(...)`
- `ensure_structural_set_method_available_for_index_assignment(...)`
- `ensure_structural_set_method_for_index_assignment(...)`
- `resolve_structural_slice_method_result_type(...)`
- `resolve_structural_set_slice_method_result_type(...)`

## `compiler/typecheck/calls.py`

Purpose:

- Own all call typing semantics.
- Separate call behavior from general expression inference.

Recommended functions:

- `infer_call_type(ctx, expr)`
- `check_call_arguments(ctx, params, args, span)`
- `infer_constructor_call_type(ctx, class_info, args, span, result_type)`
- `callable_type_from_signature(name, signature)`
- `class_type_name_from_callable(callable_name)`

This module should handle:

- top-level function calls
- imported function calls
- constructor calls
- imported constructor calls
- static-method calls
- instance-method calls
- callable field invocation
- array built-in method calls

## `compiler/typecheck/expressions.py`

Purpose:

- Own expression inference other than the details of call semantics.
- Delegate to `calls.py`, `relations.py`, `module_lookup.py`, `type_resolution.py`, and `structural.py`.

Recommended functions:

- `infer_expression_type(ctx, expr)`
- `ensure_field_access_assignable(ctx, expr)`

This module should remain readable because calls and structural protocol logic will already have been extracted.

## `compiler/typecheck/statements.py`

Purpose:

- Own statement checking and control-flow analysis.
- Keep block traversal separate from semantic relations.

Recommended functions:

- `check_function_like(ctx, params, body, return_type, receiver_type=None, owner_class_name=None)`
- `check_block(ctx, block, return_type)`
- `check_statement(ctx, stmt, return_type)`
- `block_guarantees_return(ctx, block)`
- `statement_guarantees_return(ctx, stmt)`
- `ensure_assignable_target(ctx, expr)`
- `require_member_visible(ctx, class_info, owner_type_name, member_name, member_kind, span)`

## Migration Notes

## Compatibility Strategy

- Keep the `compiler.typecheck` import path stable from the first commit.
- Keep `compiler/typecheck_model.py` temporarily as a compatibility wrapper if needed while imports are migrated.
- Move implementation in small phases and run the existing typecheck suites after each phase.

## Testing Strategy

The existing behavioral suites are already the primary safety net:

- `tests/compiler/typecheck/test_typecheck.py`
- `tests/compiler/typecheck/test_typecheck_program.py`

Add narrow unit tests only when a newly extracted module gains pure helper logic that is difficult to cover clearly through the existing end-to-end tests.

## AST Annotation Note

Today the checker mutates `ForInStmt` with derived type names. That should not be changed during the first extraction unless it becomes necessary for module boundaries.

Recommended follow-up after the refactor stabilizes:

- move derived semantic annotations into a side table keyed by node identity, or
- introduce an explicit typed-analysis result structure

## Dependency Boundaries

- Typecheck should not depend on backend/codegen internals for semantic decisions.
- The current `Str` name handling should move behind a typecheck-local helper or constant, even if it temporarily mirrors the existing spelling.
- Lower-level helper modules must not import statement or expression traversal modules.

## Implementation Sequence

## Phase 1. Prepare Stable Surface

- Convert `compiler.typecheck` from a single module file into a package facade while keeping the import path stable.
- Create `compiler/typecheck/` package skeleton.
- Move model definitions and constants into package modules.
- Add compatibility imports so callers still work during the transition.

Outcome:

- new package exists
- no semantic changes
- import churn is isolated early

## Phase 2. Extract Pure Type Relations

- Move equality, assignability, comparability, cast checks, canonicalization, and display helpers into `relations.py`.
- Move literal/operator sets and numeric bounds into `constants.py`.
- Update checker implementation to call the extracted helpers.

Status:

- implemented

Outcome:

- biggest low-risk helper cluster removed from monolith
- future type-system growth gets a dedicated home

## Phase 3. Extract Module Lookup and Type Resolution

- Move import/module/class/function lookup helpers into `module_lookup.py`.
- Move `TypeRefNode` resolution and owner qualification into `type_resolution.py`.
- Keep tests green before touching expression logic.

Status:

- implemented

Outcome:

- cross-module semantics become explicit
- expression and call code no longer own import plumbing

## Phase 4. Extract Declaration Collection

- Move pre-pass declaration collection into `declarations.py`.
- Keep the two-pass program behavior unchanged.
- Keep field-initializer constant-expression checks in this phase.

Status:

- implemented

Outcome:

- declaration pass becomes independently readable and testable

## Phase 5. Introduce Explicit Context Object

- Replace hidden mutable checker fields with `TypeCheckContext`.
- Move scope push/pop and variable declare/lookup helpers into `context.py`.
- Convert extracted helpers to accept `ctx` explicitly.

Status:

- implemented

Outcome:

- dependencies become clear
- later extractions stop depending on giant instance state

## Phase 6. Extract Call Semantics

- Move all call inference and argument checking into `calls.py`.
- Keep constructor, imported-call, callable-field, static-method, and array-method behavior intact.

Status:

- implemented

Outcome:

- one of the densest semantic areas becomes isolated

## Phase 7. Extract Structural Protocol Rules

- Move indexing, index assignment, slicing, slice assignment, and `for in` protocol rules into `structural.py`.
- Keep array built-ins and user-defined structural methods covered by existing tests.

Status:

- implemented

Outcome:

- future protocol-like features have a natural home

## Phase 8. Extract Expression Inference

- Move non-call expression inference into `expressions.py`.
- Keep call handling delegated to `calls.py`.

Status:

- implemented

Outcome:

- expression logic becomes readable because large branches are already gone

## Phase 9. Extract Statement Checking and Control Flow

- Move block, statement, assignment-target, return-path, and visibility enforcement into `statements.py`.
- Keep privacy and final-field behavior intact.

Outcome:

- remaining coordinator logic becomes small and understandable

## Phase 10. Reduce or Remove `TypeChecker`

- Convert `TypeChecker` into a thin compatibility wrapper around package-level functions, or remove it entirely if no longer useful.
- Keep only minimal orchestration in `api.py`.

Outcome:

- monolithic checker file disappears or becomes a tiny adapter

## Ordered Checklist

## A. Scaffolding

- [x] Create `compiler/typecheck/` package.
- [x] Add `api.py`, `model.py`, `context.py`, and `constants.py` skeletons.
- [x] Keep the `compiler.typecheck` import path as the stable facade by using `compiler/typecheck/__init__.py`.
- [x] Keep `compiler/typecheck_model.py` as a temporary compatibility shim during migration.

## B. Model and Constants

- [x] Move `TypeInfo`, `FunctionSig`, `ClassInfo`, and `TypeCheckError` into `compiler/typecheck/model.py`.
- [x] Move type-category sets into `compiler/typecheck/model.py` or `compiler/typecheck/constants.py` as appropriate.
- [x] Move `ARRAY_METHOD_NAMES`, literal bounds, and bitwise/operator sets into `compiler/typecheck/constants.py`.
- [x] Update imports without changing semantics.

## C. Relations

- [x] Extract type equality helpers.
- [x] Extract assignability helpers.
- [x] Extract comparability helpers.
- [x] Extract explicit-cast validation.
- [x] Extract display-format helpers for callable types.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## D. Lookup and Resolution

- [x] Extract current-module and import lookup helpers.
- [x] Extract class/function/module member resolution helpers.
- [x] Extract field-chain flattening helper.
- [x] Extract `TypeRefNode` resolution into `type_resolution.py`.
- [x] Extract owner-based member type qualification.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## E. Declaration Pass

- [x] Extract declaration pre-collection into `declarations.py`.
- [x] Extract field-initializer constant-expression validation.
- [x] Keep the two-pass `typecheck_program` flow unchanged.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## F. Context Conversion

- [x] Introduce `TypeCheckContext` dataclass.
- [x] Move scope stack operations into `context.py`.
- [x] Move variable declaration and lookup into `context.py`.
- [x] Convert extracted helpers to accept explicit `ctx`.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## G. Calls and Structural Protocols

- [x] Extract call argument checking.
- [x] Extract constructor call validation.
- [x] Extract function/static/instance/callable-field call rules.
- [x] Extract array method call rules.
- [x] Extract structural indexing and slicing helpers.
- [x] Extract `for in` iterability validation.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## H. Expressions and Statements

- [x] Extract non-call expression inference into `expressions.py`.
- [ ] Extract statement checking into `statements.py`.
- [ ] Extract return-path analysis into `statements.py`.
- [ ] Extract assignment-target validation into `statements.py`.
- [ ] Keep visibility/final-member checks stable.
- [x] Run `tests/compiler/typecheck -q` after the extraction.

## I. Final Cleanup

- [ ] Reduce `typecheck_checker.py` to a thin adapter or remove it entirely.
- [ ] Remove temporary compatibility shims that are no longer needed.
- [ ] Update repository docs that describe compiler layout.
- [ ] Run the full test suite.
- [ ] Confirm no semantic or diagnostic regressions before deleting transitional code.

## Expected End State

At the end of this refactor:

- `compiler.typecheck` remains the stable public entry point.
- core semantic policies live in focused modules instead of one large class.
- expression, call, statement, lookup, and type-relation logic have clear homes.
- future type-system extensions can be added by extending small modules instead of editing one giant file.
- the current test suites continue to validate behavior across both single-module and program-level flows.