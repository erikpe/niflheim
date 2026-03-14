# Codegen Refactor Plan

This document describes a concrete, incremental plan for splitting the current backend implementation into smaller files with clearer responsibilities.

The goal is to make the backend easier to understand, easier to test, and easier to evolve toward a later IR-based design if that becomes desirable.

## Goals

- Reduce the size and responsibility breadth of `compiler/codegen.py`.
- Separate pure planning helpers from assembly emission.
- Isolate target-specific SysV x86-64 logic from language-lowering logic.
- Keep the public backend entry point stable while refactoring internally.
- Preserve behavior throughout the refactor with focused tests at each step.

## Non-Goals

- Introduce a new IR in this refactor.
- Change the target ABI.
- Redesign the runtime call surface.
- Rewrite the whole backend in one step.

## Current Problems

`compiler/codegen.py` currently mixes several concerns that should evolve independently:

- codegen-facing type helpers
- stack frame and root-frame layout planning
- method/call target resolution
- string literal collection and encoding helpers
- SysV ABI argument/register planning
- target instruction selection
- expression lowering
- control-flow lowering
- function/module emission orchestration
- semantic normalization for signed arithmetic operations

This makes the file harder to reason about, and it raises the cost of making local changes because unrelated logic lives in the same unit.

## Target File Structure

The backend should be reorganized into a `compiler/codegen/` package.

```text
compiler/
  codegen/
    __init__.py
    model.py
    strings.py
    symbols.py
    types.py
    layout.py
    call_resolution.py
    abi_sysv.py
    asm.py
    ops_int.py
    ops_float.py
    emitter_expr.py
    emitter_stmt.py
    emitter_fn.py
    emitter_module.py
```

## File Purposes

### `compiler/codegen/__init__.py`

Purpose:
- Provide the stable public entry point, `emit_asm(module_ast)`.
- Hide the internal package layout from the rest of the compiler.

This file should stay small and orchestration-only.

### `compiler/codegen/model.py`

Purpose:
- Hold shared codegen dataclasses and configuration constants.

Owns:
- `FunctionLayout`
- `ResolvedCallTarget`
- `ConstructorLayout`
- `EmitContext`
- parameter register lists
- runtime-call metadata tables
- primitive-type sets and related constants

This is mostly the current content of `compiler/codegen_model.py`.

### `compiler/codegen/strings.py`

Purpose:
- Handle string and char literal encoding/decoding and literal discovery.

Owns:
- `decode_string_literal`
- `decode_char_literal`
- `escape_asm_string_bytes`
- `escape_c_string`
- `collect_string_literals`
- string-type helper logic

This is mostly the current content of `compiler/codegen_str_helper.py`.

### `compiler/codegen/symbols.py`

Purpose:
- Centralize backend symbol and label naming.

Owns:
- epilogue label naming
- method symbol mangling
- constructor symbol mangling
- type symbol mangling
- any other assembly-visible name construction helpers

This reduces the chance of naming policy drift.

### `compiler/codegen/types.py`

Purpose:
- Provide codegen-facing type-name helpers and source-type normalization helpers.

Owns:
- `_type_ref_name`
- array-type helpers
- function-type helpers
- primitive/reference classification
- expression type inference helpers used only by backend lowering

This file should stay pure and testable.

### `compiler/codegen/layout.py`

Purpose:
- Compute function-local stack layout and runtime root layout.

Owns:
- local collection
- slot planning
- root-slot planning
- temp-root planning
- stack-size computation
- helpers that answer whether expressions/statements need temp roots

This separates frame planning from emission.

### `compiler/codegen/call_resolution.py`

Purpose:
- Resolve what a call expression means from the backend’s point of view.

Owns:
- method target resolution
- function target resolution
- callable-value target resolution
- receiver-type lookup helpers
- field-chain flattening helpers if they only exist for call lowering

This is the semantic lowering layer between typed AST and emitted call sequences.

### `compiler/codegen/abi_sysv.py`

Purpose:
- Contain Linux x86-64 SysV ABI-specific logic.

Owns:
- parameter register/stack placement planning
- return register conventions
- helper routines for call marshaling
- any stack-alignment helper logic tied directly to ABI rules

If a new ABI is ever added, this isolation becomes important.

### `compiler/codegen/asm.py`

Purpose:
- Provide a small assembly builder abstraction and low-level formatting helpers.

Owns:
- instruction/text accumulation
- label emission helpers
- stack operand formatting helpers
- offset formatting helpers
- small utilities such as aligned stack operand rendering

This should reduce raw `self.out.append(...)` scattering.

### `compiler/codegen/ops_int.py`

Purpose:
- Emit integer-specific operator instruction sequences.

Owns:
- integer `+`, `-`, `*`, `**`
- integer `/` and `%`
- signed normalization rules for Python-style division/modulo
- bitwise and shift operators
- `u8` post-normalization masking where needed

This is the best home for the signed arithmetic semantics logic.

### `compiler/codegen/ops_float.py`

Purpose:
- Emit `double` arithmetic and comparison instruction sequences.

Owns:
- floating-point arithmetic
- floating-point comparisons
- NaN-sensitive comparison lowering if needed

This keeps float-specific target logic separate from integer logic.

### `compiler/codegen/emitter_expr.py`

Purpose:
- Lower expressions to assembly using the services from the helper modules.

Owns:
- expression evaluation order
- expression-specific temporary handling
- calls into `ops_int.py`, `ops_float.py`, `call_resolution.py`, `abi_sysv.py`

This should not own stack layout or symbol policy directly.

### `compiler/codegen/emitter_stmt.py`

Purpose:
- Lower statements and structured control flow.

Owns:
- block emission
- `if` / `while` / `for-in`
- `break` / `continue`
- assignment emission
- return-path lowering

This is the natural home for control-flow label structure.

### `compiler/codegen/emitter_fn.py`

Purpose:
- Emit functions, methods, and constructors as backend units.

Owns:
- prologue/epilogue emission
- function-local context creation
- function-body delegation to statement/expression emitters
- constructor and method wrapper generation if needed

This file should bridge planning and body emission.

### `compiler/codegen/emitter_module.py`

Purpose:
- Emit module-level assembly structure.

Owns:
- assembly preamble/sections
- string literal tables
- type metadata emission
- iteration across functions and classes
- top-level orchestration of per-function emission

This should be the highest-level backend unit.

## Refactor Principles

- Start with Phase 0 unconditionally.
- Move pure helpers first.
- Keep `emit_asm(module_ast)` stable.
- Do not change behavior and structure in the same step unless the tests force it.
- Prefer extraction over redesign for the first pass.
- Add focused tests when moving subtle logic such as signed division/modulo lowering.

## Ordered Checklist

The project should be executed in phase order.

Phase 0 is mandatory as the first step.

The later "Suggested Execution Order by Risk" section does not replace the phase order. It only describes the safest extraction order once Phase 0 and Phase 1 are complete.

### Phase 0: Stabilize the Entry Point

- [ ] Freeze `emit_asm(module_ast)` as the only public backend API.
- [ ] Add a thin package entry point under `compiler/codegen/__init__.py`.
- [ ] Keep existing imports working while the internals are moved.

### Phase 1: Move Existing Helper Modules Under a Package

- [ ] Create `compiler/codegen/` as a package.
- [ ] Move `compiler/codegen_model.py` to `compiler/codegen/model.py`.
- [ ] Move `compiler/codegen_str_helper.py` to `compiler/codegen/strings.py`.
- [ ] Update imports while keeping behavior unchanged.

### Phase 2: Extract Pure Helper Files

- [ ] Extract symbol and label helpers into `symbols.py`.
- [ ] Extract type-name and type-shape helpers into `types.py`.
- [ ] Extract stack/root layout computation into `layout.py`.
- [ ] Add or update small unit tests for extracted pure helpers when practical.

### Phase 3: Extract Semantic Lowering Helpers

- [ ] Extract call-target and callable-value resolution into `call_resolution.py`.
- [ ] Extract SysV argument-location planning into `abi_sysv.py`.
- [ ] Keep all call-resolution behavior identical during this phase.

### Phase 4: Introduce an Assembly Builder Layer

- [ ] Add `asm.py` with a small `AsmBuilder` abstraction.
- [ ] Replace direct output-list manipulation in a narrow area first.
- [ ] Convert formatting helpers such as stack-slot operand rendering to use the shared builder/utilities.

### Phase 5: Isolate Operator Lowering

- [ ] Move integer operator lowering into `ops_int.py`.
- [ ] Move `double` operator lowering into `ops_float.py`.
- [ ] Keep Python-style signed `/` and `%` normalization logic local to integer-op lowering.
- [ ] Add focused codegen tests for any moved subtle operator logic.

### Phase 6: Split Expression and Statement Emission

- [ ] Extract expression emission into `emitter_expr.py`.
- [ ] Extract statement/control-flow emission into `emitter_stmt.py`.
- [ ] Keep label generation centralized instead of duplicating it between files.

### Phase 7: Split Function and Module Emission

- [ ] Extract prologue/epilogue and per-function setup into `emitter_fn.py`.
- [ ] Extract module-level assembly orchestration into `emitter_module.py`.
- [ ] Keep constructor/method wrapper generation close to function emission.

### Phase 8: Cleanup and Simplify

- [ ] Remove dead compatibility wrappers after all imports are updated.
- [ ] Rename helpers to remove historical underscore-heavy names where clarity improves.
- [ ] Add a short backend structure summary to `docs/REPO_STRUCTURE.md` once the refactor lands.

## Suggested Extraction Order by Risk

This section applies only after Phase 0 and Phase 1 are done.

Use it to decide the safest order for the remaining extractions inside later phases, not to skip the earlier phases.

The safest extraction order is:

1. `model.py`
2. `strings.py`
3. `symbols.py`
4. `types.py`
5. `layout.py`
6. `call_resolution.py`
7. `abi_sysv.py`
8. `ops_int.py` and `ops_float.py`
9. `asm.py`
10. `emitter_expr.py`
11. `emitter_stmt.py`
12. `emitter_fn.py`
13. `emitter_module.py`

This order works because the earlier files are more pure and less entangled with mutable emission state.

## Testing Strategy During Refactor

At the end of each phase, run at least:

- focused codegen unit tests for changed logic
- affected golden arithmetic/codegen tests
- `./scripts/test.sh` after each stable phase boundary

Priority areas to protect with focused tests:

- signed integer `/` and `%` semantics
- call alignment and SysV argument placement
- string literal lowering
- temp runtime root behavior around calls
- array get/set/slice runtime helper selection
- indirect-call lowering for function values

## Practical Stop Points

Good points to pause without leaving the backend half-structured:

- after Phase 2: helpers extracted, emitter still mostly monolithic
- after Phase 5: operator logic isolated, easier to reason about arithmetic semantics
- after Phase 7: backend fully split by responsibility

## Expected Outcome

After this refactor:

- backend helper code is easier to test in isolation
- operator semantics are localized
- ABI logic is separated from AST traversal
- function/frame planning is separated from emission
- the package structure is ready for a later IR insertion if desired

This refactor should be treated as an internal architecture improvement, not a feature milestone.