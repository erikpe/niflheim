# Codegen Test Refactor Plan

This document describes a concrete plan for breaking `tests/compiler/codegen/test_codegen.py` into smaller test modules that better match the current `compiler/codegen/` package structure.

The split should improve readability, reduce import noise, make failures easier to localize, and keep the test layout aligned with the refactored backend.

## Goals

- Replace one large mixed-purpose test file with smaller files that each have a clear scope.
- Align test modules with the layered backend structure under `compiler/codegen/`.
- Separate pure helper/unit tests from emitter-layer tests and end-to-end `emit_asm` behavior tests.
- Reduce duplicated setup and imports by introducing a small shared helper layer for codegen tests.
- Keep test semantics stable while changing only organization and local helper structure.

## Non-Goals

- Redesign the backend again.
- Change backend behavior as part of the split.
- Convert these tests into golden tests.
- Force every internal helper to have a corresponding test module if that module would be nearly empty.

## Current Problems

`tests/compiler/codegen/test_codegen.py` currently mixes three different kinds of tests:

- pure helper/unit tests for low-level modules such as `asm`, `symbols`, `types`, `layout`, `abi_sysv`, and `ops_*`
- focused emitter/generator tests that construct a `CodeGenerator` and an `EmitContext`
- end-to-end `emit_asm(...)` behavior tests that exercise multiple backend layers together

This causes several practical issues:

- a single file imports almost every backend module
- failures are harder to triage because unrelated backend concerns live in one module
- file growth is unbounded because new tests naturally get appended to the same place
- the current file no longer reflects the refactored backend package structure
- test setup code is repeated in many focused emitter tests

## Guiding Structure

The split should follow backend responsibility boundaries where that improves clarity, but end-to-end behavior tests should still be grouped by language/runtime feature rather than by implementation detail.

That yields three layers of codegen tests.

### 1. Helper / Unit Tests

Purpose:

- validate pure or near-pure backend helpers in isolation
- keep these tests fast and easy to read
- avoid constructing full modules unless necessary for a specific helper API

Characteristics:

- minimal imports
- no broad `emit_asm(...)` expectations
- assertions against small helper outputs or instruction snippets

Suggested files:

- `tests/compiler/codegen/test_asm.py`
- `tests/compiler/codegen/test_symbols.py`
- `tests/compiler/codegen/test_types.py`
- `tests/compiler/codegen/test_abi_sysv.py`
- `tests/compiler/codegen/test_layout.py`
- `tests/compiler/codegen/test_call_resolution.py`
- `tests/compiler/codegen/test_ops_int.py`
- `tests/compiler/codegen/test_ops_float.py`

### 2. Emitter / Generator Layer Tests

Purpose:

- test one backend layer at a time while still working with real ASTs
- validate `CodeGenerator`, `EmitContext`, and the emitter modules directly
- keep failures localized to expression, statement, function, module, or generator coordination logic

Characteristics:

- usually parse a small source snippet
- explicitly construct `CodeGenerator`, layouts, and contexts
- assert on intermediate assembly builder output rather than full backend coverage

Suggested files:

- `tests/compiler/codegen/test_generator.py`
- `tests/compiler/codegen/test_emitter_expr.py`
- `tests/compiler/codegen/test_emitter_stmt.py`
- `tests/compiler/codegen/test_emitter_fn.py`
- `tests/compiler/codegen/test_emitter_module.py`

### 3. End-to-End `emit_asm` Behavior Tests

Purpose:

- validate user-visible codegen behavior across multiple layers
- keep feature behavior together even when the implementation spans several backend modules
- preserve the strongest regression coverage for assembly output shape and runtime interaction points

Characteristics:

- call `emit_asm(...)`
- assert on final assembly output
- group by language/runtime feature, not by internal module name

Suggested files:

- `tests/compiler/codegen/test_emit_asm_basics.py`
- `tests/compiler/codegen/test_emit_asm_calls.py`
- `tests/compiler/codegen/test_emit_asm_int_ops.py`
- `tests/compiler/codegen/test_emit_asm_strings.py`
- `tests/compiler/codegen/test_emit_asm_arrays.py`
- `tests/compiler/codegen/test_emit_asm_objects.py`
- `tests/compiler/codegen/test_emit_asm_runtime_roots.py`
- `tests/compiler/codegen/test_emit_asm_casts_metadata.py`

## Proposed Target Layout

```text
tests/compiler/codegen/
  helpers.py
  test_asm.py
  test_symbols.py
  test_types.py
  test_abi_sysv.py
  test_layout.py
  test_call_resolution.py
  test_ops_int.py
  test_ops_float.py
  test_generator.py
  test_emitter_expr.py
  test_emitter_stmt.py
  test_emitter_fn.py
  test_emitter_module.py
  test_emit_asm_basics.py
  test_emit_asm_calls.py
  test_emit_asm_int_ops.py
  test_emit_asm_strings.py
  test_emit_asm_arrays.py
  test_emit_asm_objects.py
  test_emit_asm_runtime_roots.py
  test_emit_asm_casts_metadata.py
```

This is intentionally a little finer-grained than the current state. It is acceptable to merge adjacent files later if any end up too small, but starting with clear boundaries is preferable to preserving the current aggregation problem.

## Purpose Of Each Test Group

### `helpers.py`

Purpose:

- centralize repeated codegen test setup
- keep individual test files focused on assertions rather than setup boilerplate

Recommended contents:

- a helper to lex and parse a source snippet into a module
- a helper to call `emit_asm(...)` from source text
- a helper to create `CodeGenerator` plus `EmitContext` for a named function
- small assertion helpers only if they clearly remove duplication

This helper module should stay small. It should not become a second monolithic file.

### `test_asm.py`

Purpose:

- verify `AsmBuilder` line formatting, comments, directives, labels, and operand helpers

### `test_symbols.py`

Purpose:

- verify label generation and symbol mangling helpers

### `test_types.py`

Purpose:

- verify codegen-facing type name normalization and function/array type helpers

### `test_abi_sysv.py`

Purpose:

- verify argument placement planning across integer, float, and stack-passed arguments

### `test_layout.py`

Purpose:

- verify stack slot planning, root slot planning, temp root slot planning, and stack alignment

### `test_call_resolution.py`

Purpose:

- verify call target resolution, callable value resolution, and receiver typing decisions

### `test_ops_int.py` and `test_ops_float.py`

Purpose:

- verify low-level instruction selection for operator lowering without going through full backend assembly generation

### `test_generator.py`

Purpose:

- verify generator-level coordination helpers such as aligned-call emission, location comments, and symbol table building

### `test_emitter_expr.py`

Purpose:

- verify expression-layer lowering decisions using focused assembly assertions

### `test_emitter_stmt.py`

Purpose:

- verify statement/control-flow lowering such as loops, branching, and assignment lowering

### `test_emitter_fn.py`

Purpose:

- verify function-level prologue/epilogue, debug symbol literals, parameter spill setup, and constructor function orchestration

### `test_emitter_module.py`

Purpose:

- verify section orchestration, module-level symbol tables, type metadata sections, and top-level generation flow

### `test_emit_asm_basics.py`

Purpose:

- verify basic final assembly structure
- headers, prologues/epilogues, exports, literals, simple expressions, and basic control flow

### `test_emit_asm_calls.py`

Purpose:

- verify direct calls, indirect calls, function values, argument register/stack placement, and stack alignment behavior

### `test_emit_asm_int_ops.py`

Purpose:

- verify arithmetic, bitwise operations, shifts, power, and signed division/modulo normalization at the final assembly level

### `test_emit_asm_strings.py`

Purpose:

- verify string literal collection and lowering plus `Str`-specific structural behavior

### `test_emit_asm_arrays.py`

Purpose:

- verify array construction, indexing, slicing, nested arrays, `for in`, and runtime call rooting related to arrays

### `test_emit_asm_objects.py`

Purpose:

- verify constructors, fields, methods, static methods, and structural sugar for user-defined classes

### `test_emit_asm_runtime_roots.py`

Purpose:

- verify shadow stack/root frame setup, trace ordering, runtime safepoints, temp roots, and root-slot spill behavior

### `test_emit_asm_casts_metadata.py`

Purpose:

- verify reference casts, array-kind casts, and emitted type metadata/pointer-offset metadata

## How The Current File Maps To The New Structure

The current `test_codegen.py` already contains natural clusters:

- top helper/module tests map cleanly to helper/unit and emitter-layer files
- the middle section is primarily call and operator behavior
- the latter half is mostly arrays, objects, runtime/rooting, and type metadata

The split should preserve test names where possible so `git blame` and failure history remain easy to follow.

## Refactor Rules

During implementation, keep the following rules:

- Do not rewrite assertions unless they are clearly coupled to the new helper structure.
- Prefer moving tests unchanged first, then simplifying imports/setup second.
- Avoid importing nearly every backend module in every test file.
- Keep helper/unit tests independent from `emit_asm(...)` where possible.
- Keep end-to-end tests feature-oriented, even if they touch several backend modules.
- Keep `helpers.py` small and mechanical; if it grows too much, split helper creation by concern.

## Ordered Implementation Checklist

### Phase 0: Preparation

- [x] Add this plan document to the docs set.
- [x] Identify repeated setup patterns in `test_codegen.py`.
- [x] Decide whether shared helpers live in `helpers.py` or `conftest.py`.

### Phase 1: Shared Test Helpers

- [x] Create `tests/compiler/codegen/helpers.py`.
- [x] Add a source-to-module helper.
- [x] Add a source-to-assembly helper.
- [x] Add a helper for constructing `CodeGenerator` + `EmitContext` for a selected function.
- [x] Keep helper APIs minimal and focused.

### Phase 2: Extract Pure Helper / Unit Tests

- [x] Move asm builder and operand helper tests into `test_asm.py`.
- [x] Move symbol helper tests into `test_symbols.py`.
- [x] Move type helper tests into `test_types.py`.
- [x] Move SysV argument planning tests into `test_abi_sysv.py`.
- [x] Move layout planning tests into `test_layout.py`.
- [x] Move call resolution tests into `test_call_resolution.py`.
- [x] Move float-op tests into `test_ops_float.py`.
- [x] Move integer-op tests into `test_ops_int.py`.
- [x] Run the extracted tests.

### Phase 3: Extract Emitter / Generator Tests

- [x] Move generator coordination tests into `test_generator.py`.
- [x] Move focused expression emitter tests into `test_emitter_expr.py`.
- [x] Move focused statement emitter tests into `test_emitter_stmt.py`.
- [x] Move focused function emitter tests into `test_emitter_fn.py`.
- [x] Move focused module emitter tests into `test_emitter_module.py`.
- [x] Run the emitter-layer tests.

### Phase 4: Extract End-to-End Basics

- [x] Move final-assembly basics into `test_emit_asm_basics.py`.
- [x] Keep simple literals, control flow, exports, and basic prologue/epilogue coverage there.
- [x] Run that subset.

### Phase 5: Extract Call Behavior

- [x] Move direct call tests into `test_emit_asm_calls.py`.
- [x] Move indirect/function-value call tests into `test_emit_asm_calls.py`.
- [x] Move register/stack argument order and alignment tests there.
- [x] Run that subset.

### Phase 6: Extract Arithmetic / Integer Behavior

- [x] Move arithmetic, bitwise, shift, power, and signed div/mod tests into `test_emit_asm_int_ops.py`.
- [x] Run that subset.

### Phase 7: Extract Strings, Arrays, Objects

- [x] Move string literal and `Str` behavior tests into `test_emit_asm_strings.py`.
- [x] Move array lowering tests into `test_emit_asm_arrays.py`.
- [x] Move constructor/field/method/object sugar tests into `test_emit_asm_objects.py`.
- [x] Run each subset.

### Phase 8: Extract Runtime Roots / Casts / Metadata

- [x] Move GC root-frame and safepoint tests into `test_emit_asm_runtime_roots.py`.
- [x] Move cast and type metadata tests into `test_emit_asm_casts_metadata.py`.
- [x] Run each subset.

### Phase 9: Final Cleanup

- [x] Remove now-empty or near-empty leftovers from `test_codegen.py`.
- [x] Delete `test_codegen.py` once all tests are moved.
- [x] Normalize import order and helper usage across the new files.
- [x] Run `pytest tests/compiler/codegen -q`.
- [x] Run the full test suite.

## Recommended Execution Order

The safest execution order is:

1. shared helpers
2. pure helper/unit tests
3. emitter/generator tests
4. end-to-end `emit_asm` tests by feature cluster
5. final deletion of `test_codegen.py`

This order keeps the remaining monolithic file shrinking in a controlled way while preserving a runnable suite after each step.

## Acceptance Criteria

The refactor is complete when all of the following are true:

- `test_codegen.py` is gone or reduced to a short transitional shim that can be deleted immediately after the next step
- each new file has a clear scope visible from its name alone
- helper/unit tests no longer depend on broad `emit_asm(...)` setup unless truly necessary
- emitter-layer tests use shared focused setup helpers instead of repeating large setup blocks
- end-to-end tests are grouped by language/runtime feature
- `pytest tests/compiler/codegen -q` remains green
- the full repository test suite remains green