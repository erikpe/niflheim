# Semantic Lowering Refactor Plan

This document defines a concrete refactor plan for simplifying `compiler/semantic/lowering.py`.

The main drivers are:

- improve readability
- reduce complexity and mental load
- narrow module responsibilities
- create small, explicit interfaces between lowering subdomains
- make future semantic-lowering changes safer and easier to review

This plan is intentionally incremental. The goal is to improve structure without changing lowering behavior.

The public entry point remains `compiler.semantic.lowering`. The internal helper modules now live under `compiler/semantic/lowering/` as the refactor proceeds.

## Goals

- split `compiler/semantic/lowering.py` into smaller, focused modules
- separate orchestration, statement lowering, expression lowering, resolution, dispatch, and ID helpers
- keep the public lowering entry point stable
- preserve current semantic IR shape and behavior during the refactor
- make each extracted module readable in isolation

## Non-Goals

- do not redesign semantic IR
- do not change language behavior
- do not rewrite lowering around a visitor framework
- do not combine this work with unrelated semantic or typecheck refactors
- do not change codegen or runtime interfaces as part of the structural split

## Current Problems

`compiler/semantic/lowering.py` is large, but the main issue is not size alone. It mixes multiple distinct concerns in one file.

Main problems:

1. one file owns program/module orchestration, declaration lowering, statement lowering, expression lowering, call resolution, reference resolution, lvalue resolution, collection special cases, literal lowering, and symbol-ID helpers
2. internal `Resolved*Target` dataclasses for unrelated subdomains all live together at module top level
3. expression lowering repeatedly jumps between semantic questions:
   - what does this AST node resolve to?
   - what type does it have?
   - what semantic IR node should represent it?
4. array/slice/collection lowering logic is split across generic expression and statement lowering instead of having one clear home
5. type-name-to-ID utilities are coherent as a group but buried at the bottom of an unrelated file
6. many helpers are readable individually, but the file as a whole is expensive to scan and reason about safely

## Current Responsibility Clusters

The file already contains natural seams that can become module boundaries.

### Program And Declaration Lowering

- `lower_program(...)`
- `_build_typecheck_contexts(...)`
- `_lower_module(...)`
- `_lower_interface(...)`
- `_lower_interface_method(...)`
- `_lower_class(...)`
- `_lower_field(...)`
- `_lower_function(...)`
- `_lower_method(...)`
- `_lower_param(...)`

### Statement And Scope Lowering

- `_lower_function_like_body(...)`
- `_lower_block(...)`
- `_lower_stmt(...)`

### Expression Lowering

- `_lower_expr(...)`
- `_lower_call_expr(...)`
- `_lower_non_string_literal_expr(...)`
- `_lowered_literal_type_name(...)`
- `_lower_string_literal_expr(...)`
- `_try_lower_string_concat_expr(...)`

### Call, Reference, And LValue Resolution

- `_resolve_call_target(...)`
- `_resolve_identifier_call_target(...)`
- `_resolve_field_access_call_target(...)`
- `_resolve_module_member_call_target(...)`
- `_resolve_identifier_ref_target(...)`
- `_resolve_field_access_ref_target(...)`
- `_resolve_lvalue_target(...)`
- `_lower_resolved_ref(...)`
- `_lower_lvalue(...)`

### Array, Slice, And Collection Special Cases

- `_try_lower_array_structural_call_expr(...)`
- `_try_lower_slice_assign_stmt(...)`
- `_try_lower_array_index_assign_stmt(...)`
- `_try_lower_array_slice_assign_stmt(...)`
- `_try_lower_slice_read_expr(...)`
- `_resolve_collection_dispatch(...)`
- `_runtime_dispatch_for_array_operation(...)`
- `_array_runtime_kind(...)`

### Type Name And Symbol-ID Helpers

- `_resolve_instance_method_id(...)`
- `_resolve_static_method_id(...)`
- `_function_id_for_local_name(...)`
- `_function_id_for_imported_name(...)`
- `_function_id_for_module_member(...)`
- `_class_id_for_module_member(...)`
- `_constructor_id_for_module_member(...)`
- `_class_id_from_type_name(...)`
- `_constructor_id_from_type_name(...)`
- `_method_id_for_type_name(...)`
- `_interface_id_for_type_name(...)`
- `_interface_method_id_for_type_name(...)`
- `_split_type_name(...)`

## Target Structure

The lowering code should move toward a package structure like this:

- `compiler/semantic/lowering/__init__.py`
  - public `lower_program(...)` re-export only
- `compiler/semantic/lowering/orchestration.py`
  - public entry point
  - typecheck-context setup
  - module/class/function/interface lowering
  - shared lowering context type
- `compiler/semantic/lowering/statements.py`
  - block lowering
  - function-body scope setup
  - statement lowering
- `compiler/semantic/lowering/expressions.py`
  - expression lowering
  - call lowering integration
  - literal and string-special-case lowering
- `compiler/semantic/lowering/calls.py`
  - call target resolution only
  - call-resolution internal dataclasses and unions
- `compiler/semantic/lowering/references.py`
  - identifier/field reference resolution
  - lvalue resolution
  - reference/lvalue lowering adapters
- `compiler/semantic/lowering/collections.py`
  - array structural calls
  - slice read/write lowering
  - collection dispatch helpers
- `compiler/semantic/lowering/ids.py`
  - type-name parsing
  - function/class/constructor/method/interface ID helpers
- `compiler/semantic/lowering/literals.py`
  - literal-specific lowering helpers and type-name quirks

This keeps the public lowering entry point stable while making internal concerns much narrower.

## Shared Context And Internal Types

Keep a shared lowering context, but keep it small.

Recommended shared type:

- `_ModuleLoweringContext`
  - `typecheck_ctx`
  - `symbol_index`

Recommended ownership for internal dataclasses:

- call-target dataclasses belong in `calls.py`
- ref/lvalue-target dataclasses belong in `references.py`
- they should not remain in a central file once their logic is extracted

## Ordered Checklist

Use this order. It minimizes risk and removes complexity from the current file in coherent chunks.

1. Extract `ids.py`
  - [x] create `compiler/semantic/lowering/ids.py`
   - [x] move `_split_type_name(...)`
   - [x] move all `_*_id_*` helpers
   - [x] update lowering call sites to import through the new module
   - [x] keep behavior identical for qualified and unqualified type names
   - Validation:
     - focused semantic lowering tests
     - tests that exercise imported names, methods, constructors, and interfaces

2. Extract `collections.py`
  - [x] create `compiler/semantic/lowering/collections.py`
  - [x] move array structural call lowering helpers
  - [x] move slice read/write lowering helpers
  - [x] move collection dispatch helpers
  - [x] keep matching order and dispatch behavior unchanged
   - Validation:
     - semantic lowering tests for arrays, indexing, slicing, and `for-in`

3. Extract `literals.py`
  - [x] create `compiler/semantic/lowering/literals.py`
  - [x] move `_lower_non_string_literal_expr(...)`
  - [x] move `_lowered_literal_type_name(...)`
  - [x] move `_lower_string_literal_expr(...)`
  - [x] move `_try_lower_string_concat_expr(...)`
  - [x] preserve the unsuffixed min-`i64` special case exactly
   - Validation:
     - semantic lowering tests for int/float/bool/char/string literals
     - tests covering string concatenation lowering

4. Extract `calls.py`
  - [x] create `compiler/semantic/lowering/calls.py`
  - [x] move `_resolve_call_target(...)`
  - [x] move identifier/field/module-member call target helpers
  - [x] move call-target internal dataclasses and union aliases
  - [x] keep callable-value fallback behavior unchanged
   - Validation:
     - semantic lowering tests for function, method, constructor, interface, and callable-value calls

5. Extract `references.py`
  - [x] create `compiler/semantic/lowering/references.py`
  - [x] move identifier/field reference target resolution
  - [x] move lvalue target resolution
  - [x] move `_lower_resolved_ref(...)`
  - [x] move `_lower_lvalue(...)`
  - [x] move ref/lvalue internal dataclasses and union aliases
   - Validation:
     - semantic lowering tests for locals, fields, methods-as-values, and assignment targets

6. Extract `statements.py`
  - [x] create `compiler/semantic/lowering/statements.py`
  - [x] move `_lower_function_like_body(...)`
  - [x] move `_lower_block(...)`
  - [x] move `_lower_stmt(...)`
  - [x] keep scope push/pop behavior unchanged
  - [x] keep private-owner setup and restoration unchanged
   - Validation:
     - semantic lowering tests for control flow, locals, `for-in`, returns, and nested blocks

7. Extract `expressions.py`
  - [x] create `compiler/semantic/lowering/expressions.py`
  - [x] move `_lower_expr(...)`
  - [x] move `_lower_call_expr(...)`
  - [x] keep expression dispatch readable and thin by delegating special cases outward
   - Validation:
     - semantic lowering tests for the full expression surface

8. Extract `orchestration.py`
   - [x] create `compiler/semantic/lowering/orchestration.py`
   - [x] move `lower_program(...)`
   - [x] move `_build_typecheck_contexts(...)`
   - [x] move declaration/module lowering helpers
   - [x] keep `_ModuleLoweringContext` here unless a better shared home emerges naturally during extraction
   - Validation:
     - full semantic lowering suite
     - resolver/typecheck/semantic integration tests

9. Add package entry point
  - [x] add `compiler/semantic/lowering/__init__.py`
   - [x] re-export only `lower_program`
   - [x] replace old import sites to use the package entry point if needed
  - [x] remove or replace the old monolithic file only after the split is complete
   - Validation:
     - full compiler test suite

## Success Criteria Per Step

Each step should leave the codebase in a better state immediately.

After each extraction step:

- the moved subdomain has one obvious home
- the remaining lowering code reads more linearly than before
- the extracted module has a small, explicit dependency surface
- no behavioral changes are introduced
- focused tests pass before moving on

## Invariants To Preserve

These behaviors are subtle and must stay unchanged through the refactor.

1. Unsuffixed minimum `i64` literal handling
   - preserve the special case in literal type-name lowering

2. Function-like body scope restoration
   - preserve `current_private_owner_type` save/restore behavior
   - preserve local-scope push/pop ordering

3. `for-in` element scoping
   - preserve the exact loop-variable scope lifetime

4. Array/slice structural matching order
   - preserve guard ordering for array-vs-non-array structural calls

5. Module-member resolution behavior
   - preserve current distinction between functions, classes, and unsupported module references

6. Symbol-ID construction behavior
   - preserve handling of qualified type names and current-module defaults

7. Callable-value fallback behavior
   - preserve the current fallback from explicit call target resolution to callable-value lowering

## Validation Strategy

Run focused tests after every extraction step, then run a broader semantic slice periodically.

Recommended focused validation:

- semantic lowering tests
- parser and typecheck tests if a step touches AST interpretation assumptions
- collection/array tests after `collections.py`
- string/literal tests after `literals.py`

Recommended periodic broader validation:

- full `tests/compiler/semantic`
- full `tests/compiler/typecheck`
- selected codegen smoke tests that exercise semantic lowering output shape

## Recommended First Step

Start with `ids.py`.

Why:

- it is the most self-contained utility cluster
- it has clear boundaries already
- it removes a large, low-level tail from the file
- it creates reusable helpers needed by later `calls.py` and `references.py` extraction

## Status

All planned semantic lowering refactor steps are complete.

The package entry point now re-exports only `lower_program`, internal lowering concerns have dedicated module homes, and broad semantic/typecheck validation has passed after the final package cleanup.

Checklist completion should be updated in this document as the refactor progresses.