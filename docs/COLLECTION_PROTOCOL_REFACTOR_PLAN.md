# Collection Protocol Refactor Plan

This document describes a focused refactor for centralizing the language-visible names used by collection sugaring and structural protocol handling.

Update: Steps 1 through 9 are now implemented. The remaining work in this plan is validation/documentation sync.

The current pipeline still uses raw strings such as `len`, `index_get`, `index_set`, `slice_get`, `slice_set`, `iter_len`, and `iter_get` in multiple phases.

Those names currently serve three different purposes:

- language surface spellings seen in source code
- semantic operation identity used by lowering and IR shaping
- backend runtime target selection such as `rt_array_len` and `rt_array_get_i64`

That overlap makes the code harder to maintain, because the same concept is repeated in parser, typecheck, semantic lowering, semantic tests, and some backend-adjacent logic.

## Goals

- centralize language-visible collection protocol names in one phase-neutral place
- stop passing raw protocol-name strings through semantic lowering helpers
- keep backend runtime symbol spelling out of parser, typecheck, and semantic logic
- make each pipeline phase own only the collection knowledge appropriate to that phase

## Non-Goals

- change the user-facing language spellings
- redesign runtime function naming
- change collection semantics or structural protocol rules
- widen Step 6 back into another codegen-behavior refactor

## Current Problem

The current code still mixes protocol names across phases.

Examples:

- parser rewrites sugared forms using raw field-name strings such as `len`, `slice_get`, and `slice_set`
- typecheck validates structural protocol members using raw names such as `iter_len`, `iter_get`, `index_get`, and `slice_set`
- semantic lowering historically switched on raw field names and passed string parameters like `method_name="index_get"` and `array_operation="get"`
- semantic runtime dispatch historically carried backend call-name strings directly, which blurred the semantic/codegen boundary

This creates three maintainability problems:

1. language-level protocol names are not defined in a single source of truth
2. semantic lowering used stringly-typed helper APIs before operation kinds were introduced
3. backend runtime symbol names were too easy to confuse with source-visible protocol names before runtime dispatch became backend-neutral

## Recommended Ownership

### Common: language-visible protocol names

Create a new phase-neutral module:

- `compiler/common/collection_protocols.py`

This module should define the source-visible names used by collection sugaring and structural protocol validation.

Recommended contents:

- `COLLECTION_METHOD_LEN = "len"`
- `COLLECTION_METHOD_INDEX_GET = "index_get"`
- `COLLECTION_METHOD_INDEX_SET = "index_set"`
- `COLLECTION_METHOD_SLICE_GET = "slice_get"`
- `COLLECTION_METHOD_SLICE_SET = "slice_set"`
- `COLLECTION_METHOD_ITER_LEN = "iter_len"`
- `COLLECTION_METHOD_ITER_GET = "iter_get"`

Recommended grouped sets:

- `COLLECTION_PROTOCOL_METHOD_NAMES`
- `INDEXING_PROTOCOL_METHOD_NAMES`
- `SLICING_PROTOCOL_METHOD_NAMES`
- `ITERATION_PROTOCOL_METHOD_NAMES`

These names are part of the language surface, so they should not live only under typecheck.

### Semantic: normalized operation identity

Semantic lowering should stop passing raw protocol-name strings through helper calls.

Instead, define one canonical semantic operation identity, either in:

- `compiler/common/collection_protocols.py`

or, if you want to keep it semantic-owned:

- `compiler/semantic/ir.py`

Recommended shape:

- `CollectionOpKind.LEN`
- `CollectionOpKind.INDEX_GET`
- `CollectionOpKind.INDEX_SET`
- `CollectionOpKind.SLICE_GET`
- `CollectionOpKind.SLICE_SET`
- `CollectionOpKind.ITER_LEN`
- `CollectionOpKind.ITER_GET`

Lowering should convert source spellings into one of these kinds as early as possible.

### Codegen: runtime symbol spelling

Backend runtime symbol names should remain codegen-owned.

Examples:

- `rt_array_len`
- `rt_array_get_i64`
- `rt_array_set_ref`
- `rt_array_slice_double`

These names should not move into `compiler/common/`, because they are backend/runtime implementation details rather than language surface.

## Recommended Phase Responsibilities

### Parser

Parser should only know the language-visible protocol names needed for sugaring rewrites.

Parser should:

- import protocol-name constants from `compiler/common/collection_protocols.py`
- use those constants instead of embedded literals when rewriting sugar

Parser should not:

- know runtime call names
- know semantic dispatch kinds

### Typecheck

Typecheck should own the structural validation rules for these protocols.

Typecheck should:

- use centralized protocol-name constants
- validate required arity, return types, parameter types, and visibility
- continue producing diagnostics in terms of source-visible names

Typecheck should not:

- invent another local source of truth for the protocol spellings

### Semantic lowering

Semantic lowering should be the only phase that decides how a collection operation is normalized.

Lowering should:

- translate protocol spellings into `CollectionOpKind`
- decide whether the operation is method-backed or runtime-backed
- produce normalized semantic dispatch records from that decision

Lowering should not:

- keep taking raw `method_name` and `array_operation` string parameters after this refactor

### Semantic IR

Semantic IR should carry normalized dispatch data, not raw protocol spellings.

The current Step 6 dispatch model is a good intermediate state.

The cleaner target state is:

- method-backed operations use resolved method identity
- runtime-backed operations use structured runtime operation data rather than raw backend call-name strings

### Codegen

Codegen should consume normalized dispatch only.

Codegen should:

- map runtime-backed collection operations to backend symbol names
- emit resolved method calls for method-backed operations

Codegen should not:

- switch on source-visible protocol names such as `index_get` or `iter_len`

## Recommended Refactor Shape

The cleanest incremental approach is a two-layer model.

### Layer 1: centralize source-visible protocol names

Add one common module for the language spellings and shared sets.

This immediately removes duplication across parser, typecheck, and lowering.

### Layer 2: centralize semantic operation identity

Add a normalized operation-kind enum and convert lowering helpers to use it instead of raw strings.

This removes the remaining stringly-typed semantic APIs introduced before and around Step 6.

### Layer 3: make runtime dispatch backend-neutral

Replace `RuntimeDispatch(call_name=...)` with structured runtime operation metadata.

For example, semantic dispatch could carry:

- operation kind
- runtime element kind

Then codegen would map that structured information to concrete runtime symbols.

This is cleaner architecturally and is now implemented.

## Suggested Module Layout

Recommended new shared module:

- `compiler/common/collection_protocols.py`

Possible contents:

- protocol-name constants
- grouped sets
- optional `CollectionOpKind`
- optional helpers such as `collection_op_from_method_name(...)`

Likely consumers:

- `compiler/frontend/parser.py`
- `compiler/typecheck/constants.py`
- `compiler/typecheck/structural.py`
- `compiler/semantic/lowering.py`

Backend helper used by the implemented Layer 3:

- `compiler/codegen/runtime_calls.py`

## Ordered Checklist

1. Create `compiler/common/collection_protocols.py`.
2. Move the current collection protocol name set out of `compiler/typecheck/constants.py` into that new common module.
3. Replace raw protocol-name literals in `compiler/frontend/parser.py` with imports from the new common module.
4. Replace raw protocol-name literals in `compiler/typecheck/structural.py` with imports from the new common module.
5. Replace raw protocol-name literals in `compiler/semantic/lowering.py` with imports from the new common module.
6. Introduce a normalized `CollectionOpKind` enum and convert lowering helpers to take operation kinds instead of `method_name` and `array_operation` strings.
7. Update semantic tests to assert the normalized operation-kind behavior where appropriate instead of relying on embedded protocol strings.
8. Keep runtime symbol spelling codegen-owned and verify that no parser, typecheck, or semantic module imports runtime call-name constants.
9. Replace `RuntimeDispatch(call_name=...)` with backend-neutral structured runtime dispatch so semantic carries operation identity and runtime kind rather than backend call-name strings.
10. Run focused parser, typecheck, lowering, and codegen collection-operation tests, then run full `pytest`.

## Implementation Status

- Step 1: implemented
- Step 2: implemented
- Step 3: implemented
- Step 4: implemented
- Step 5: implemented
- Step 6: implemented
- Step 7: implemented
- Step 8: implemented
- Step 9: implemented
- Step 10: implemented and validated

The implemented Step 9 shape is:

- `RuntimeDispatch(operation=CollectionOpKind..., runtime_kind=ArrayRuntimeKind | None)` in semantic IR
- `runtime_dispatch_call_name(...)` in codegen mapping that structured data to concrete runtime symbols
- no backend runtime symbol spellings in parser, typecheck, or semantic modules

Validation performed across the rollout included:

- focused parser, typecheck, semantic, and codegen slices for collection operations
- focused runtime-dispatch/codegen tests after the backend-neutral dispatch change
- repeated full `pytest` runs

Current Step 10 validation results:

- focused slice: `161 passed`
- full suite: `532 passed`

Focused Step 10 slice executed in this final validation pass:

- `tests/compiler/frontend/parser/test_parser.py`
- `tests/compiler/typecheck/test_structural.py`
- `tests/compiler/semantic/test_lowering.py`
- `tests/compiler/semantic/test_reachability.py`
- `tests/compiler/codegen/test_emit_asm_arrays.py`
- `tests/compiler/codegen/test_emit_asm_objects.py`
- `tests/compiler/codegen/test_runtime_calls.py`

## Validation Targets

Focused areas for this refactor should include:

- parser sugaring tests
- typecheck structural collection protocol tests
- semantic lowering tests for collection dispatch
- semantic reachability tests for method-backed iteration/indexing
- codegen tests for array runtime calls and structural method dispatch

Suggested focused test files:

- `tests/compiler/frontend/parser/test_parser.py`
- `tests/compiler/typecheck/test_structural.py`
- `tests/compiler/semantic/test_lowering.py`
- `tests/compiler/semantic/test_reachability.py`
- `tests/compiler/codegen/test_emit_asm_arrays.py`
- `tests/compiler/codegen/test_emit_asm_objects.py`

## Completion Criteria

This refactor is complete when all of the following are true:

- source-visible collection protocol names are defined in exactly one shared module
- parser, typecheck, and semantic lowering import those names instead of embedding literals
- semantic lowering no longer passes raw protocol-name strings through helper APIs
- runtime-backed semantic dispatch is backend-neutral rather than carrying concrete call-name strings
- codegen no longer depends on source-visible protocol spellings
- backend runtime symbol names remain codegen-owned
