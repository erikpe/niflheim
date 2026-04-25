# Backend IR Transition Plan

Status: proposed.

This document describes a phased plan for introducing a real backend IR and fully transitioning the compiler backend to use it.

The concrete backend IR v1 schema is defined in [docs/BACKEND_IR_SPEC.md](BACKEND_IR_SPEC.md).

The plan is intentionally focused on:

- correctness first
- readability and maintainability over early performance
- a clear target-neutral backend boundary
- feature parity with the current implementation before optimization work
- passing the full golden test suite before the legacy backend path is removed

The first backend delivered by this plan is `x86-64 SysV`.

The backend IR is designed so that future backends such as `aarch64` can reuse the same IR and most of the same middle-end analyses.

## Why This Change Is Needed

The current checked pipeline is:

- resolve
- typecheck
- lower to semantic IR
- optimize semantic IR
- link semantic IR
- lower linked semantic IR into the current executable/lowered semantic form
- emit `x86-64 SysV` assembly directly from that structured form

That pipeline works, but it has a structural limitation: the compiler's backend analyses are spread across the current codegen package instead of being expressed through one explicit backend IR.

Today:

- the semantic IR explicitly avoids becoming a low-level backend IR
- the executable/lowered semantic program is still structured semantic IR, not CFG
- control-flow-sensitive backend reasoning such as root liveness and stack planning is performed by tree walks over statements and expressions
- the current backend mixes target-neutral concerns with `x86-64 SysV`-specific emission

The loop-root-clearing workaround in the current backend is the clearest sign that the compiler has outgrown statement-tree backend analysis. A real CFG-based backend IR is the correct next seam.

## Goals

- Introduce a target-neutral backend IR between semantic lowering/linking and target emission.
- Make the backend IR serializable for debugging, inspection, and deterministic test fixtures.
- Use a register-based, three-address-code IR from the start.
- Make the backend IR CFG-based from the start.
- Do not require SSA in the first version.
- Preserve a clean path to future SSA construction and CFG-based optimization work.
- Move backend analyses such as liveness, safepoint/root planning, and stack-home planning onto the backend IR.
- Deliver one complete target backend: `x86-64 SysV`.
- Reach behavioral parity with the current implementation and pass the current full golden test suite.

## Non-Goals

- Do not pursue performance parity in this plan.
- Do not introduce a global register allocator in the first transition.
- Do not introduce full SSA, dominator-based optimization, or LICM in the first transition.
- Do not implement `aarch64` in the first transition.
- Do not redesign semantic IR at the same time as backend IR.
- Do not mix backend IR migration with unrelated runtime redesigns.

## Migration Principles

Use these rules throughout the transition:

1. Keep the semantic IR as the semantic source of truth.
2. Keep the new backend IR target-neutral: no physical registers, no stack offsets, no assembly syntax.
3. Preserve source spans and stable IDs throughout lowering so backend dumps stay debuggable.
4. Keep the legacy backend path available until the new path passes its phase gate.
5. Prefer deterministic data structures and deterministic serialization from the beginning.
6. Keep the initial target backend simple, even if it is slower.
7. Keep backend analyses explicit and testable rather than embedded in emitters.

## Final Target Pipeline

The final checked pipeline after this transition should be:

- resolve
- typecheck
- lower to semantic IR
- optimize semantic IR
- link semantic IR
- lower to backend IR
- run required backend IR verification and correctness passes
- lower backend IR to `x86-64 SysV`
- emit assembly

Conceptually:

```python
program = resolve_program(entry)
typecheck_program(program)
semantic_program = lower_program(program)
optimized_program = optimize_semantic_program(semantic_program)
linked_program = link_semantic_program(optimized_program)
backend_program = lower_to_backend_ir(linked_program)
verified_program = run_backend_ir_pipeline(backend_program)
asm = emit_x86_64_sysv_asm(verified_program)
```

The semantic IR remains a structured semantic representation.

The backend IR becomes the single backend input.

## Recommended Package Layout

Introduce a new backend package instead of expanding the existing `compiler/codegen/` package further.

Recommended layout:

```text
compiler/
  backend/
    ir/
      model.py
      serialize.py
      text.py
      verify.py
    lowering/
      program.py
      functions.py
      expressions.py
      control_flow.py
    analysis/
      cfg.py
      simplify_cfg.py
      liveness.py
      safepoints.py
      root_slots.py
      stack_homes.py
      block_order.py
    program/
      symbols.py
      class_hierarchy.py
      metadata.py
    targets/
      x86_64_sysv/
        abi.py
        frame.py
        lower_calls.py
        instruction_selection.py
        emit.py
        asm.py
```

During migration, existing modules in `compiler/codegen/` can remain as compatibility shims or reference implementations. The transition does not need a package rename in phase 1.

## Backend IR V1 Requirements

### 1. Register-Based Three-Address Code

Backend IR v1 should be register-based and explicitly three-address-code-like.

Requirements:

- instructions take explicit operands and at most one destination
- operands are virtual registers, immediates, block labels, or global/backend symbols
- no target-specific two-address constraints in the IR
- no physical register names in the IR

This keeps the IR readable and target-neutral while still being a strong base for later instruction selection.

### 2. CFG From Day One

Backend IR v1 should represent each function-like body as:

- a list or map of basic blocks
- explicit predecessors and successors derivable from terminators
- explicit terminators such as `jump`, `branch`, `return`, and `trap`

There should be no hidden control flow inside structured `if`/`while` nodes at the backend IR layer.

### 3. Not SSA In V1

Backend IR v1 should not require SSA.

Recommended approach:

- virtual registers are mutable and may be assigned more than once
- lowering inserts explicit copies where needed at control-flow joins
- merge points are represented with ordinary moves/copies, not phi nodes or block parameters

This keeps the first transition simpler while still removing the current tree-walk limitations.

### 4. SSA-Friendly Design

Even though v1 is not SSA, it should be easy to convert later.

Design constraints for that:

- stable block IDs
- stable instruction IDs
- explicit def/use tracking utilities
- explicit predecessor/successor relations
- explicit copies at joins instead of hidden variable merging
- verifier rules that make later SSA construction mechanical

SSA conversion can then be a later pass that rewrites mutable virtual registers into SSA values plus phi nodes or block parameters.

### 5. Serializable And Inspectable

Backend IR must be serializable for debugging, testing, and inspection.

Required formats:

- canonical JSON for deterministic machine-readable snapshots
- human-readable text dump for review and debugging

Required properties:

- explicit format version
- deterministic ordering of functions, blocks, registers, and instructions
- round-trip parse/write tests for JSON
- stable text formatting suitable for golden-style test fixtures

Recommended CLI/debug hooks:

- `--dump-backend-ir text`
- `--dump-backend-ir json`
- `--dump-backend-ir-dir <dir>`
- `--stop-after backend-ir`
- `--stop-after backend-ir-passes`

### 6. Target Neutrality

Backend IR v1 should be useful to more than one target backend.

That means:

- no `x86-64` register names
- no frame-pointer-relative offsets
- no direct assembly labels as the primary identity for globals
- no hardcoded SysV argument location rules in IR nodes

Target-dependent work belongs in target backends and ABI descriptors.

### 7. GC/Safepoint Awareness

The backend IR needs to carry enough information for correct GC/root handling.

Requirements:

- call-like operations declare whether they may trigger GC or otherwise act as safepoints
- reference-typed virtual registers stay typed at the backend IR layer
- analyses can compute live reference sets at safepoints from CFG liveness
- root-slot assignment is derived from backend IR analyses, not statement-tree walks

## Backend IR V1 Scope

The initial backend IR should be rich enough to cover the current feature set without forcing early low-level lowering.

Recommended operation families:

- constants and copies
- arithmetic and comparisons
- boolean tests and branches
- direct calls
- virtual/interface/runtime-dispatch calls
- object and array loads/stores through target-neutral ops or explicit runtime-backed ops
- casts and type tests
- null checks and bounds checks
- returns and traps

The IR should not attempt to encode raw assembly-like machine instructions.

## Required Backend IR Passes In Scope

This plan only includes the passes needed to replace the current implementation correctly.

Required in-scope passes:

- backend IR verifier
- CFG construction verification
- unreachable block elimination
- basic CFG simplification
- predecessor/successor indexing
- virtual-register liveness
- safepoint/reference liveness
- named root slot planning
- stack-home planning for virtual registers and temporaries
- deterministic block ordering for emission
- target-specific call/legalization lowering required by `x86-64 SysV`

Useful but optional in-scope cleanup passes:

- trivial copy elimination where it does not complicate correctness
- fallthrough simplification
- empty block forwarding

## Deferred Passes

These should be deliberately deferred until after the transition is complete:

- SSA construction
- dominator tree construction for optimization
- phi/block-parameter representation
- dead code elimination beyond simple unreachable CFG cleanup
- global value numbering
- CSE
- loop invariant motion
- full register allocation
- target-independent instruction scheduling

## Final Backend Strategy For V1

The initial `x86-64 SysV` backend should favor simplicity over speed.

Recommended strategy:

- lower backend virtual registers to stack-backed homes
- use a small, disciplined set of scratch physical registers during emission
- avoid a real register allocator in v1
- keep calling-convention handling explicit and local to the target backend

This is slower than a mature backend, but it keeps the first transition readable and correct.

The same strategy can be reused by a future `aarch64` backend with a different ABI descriptor and a different set of scratch registers.

## Program-Global Backend Context

Not all backend work belongs inside per-function IR.

The final backend path should separate:

- per-function backend IR
- program-global backend context

Program-global backend context should own:

- symbol naming / mangling
- class hierarchy indexing
- field layout
- virtual slot layout
- interface slot layout
- runtime metadata records
- string literal pooling

This avoids mixing global metadata discovery with per-function instruction emission.

## Phased Transition Plan

## Pre-Phase-1 Freeze Checklist

The following decisions are frozen for this plan:

- lowering seam: backend IR lowers from `LinkedSemanticProgram` directly. The current executable/lowered semantic form may remain temporarily as a legacy-backend compatibility artifact during migration, but it is not the source contract for backend IR.
- constructor representation: backend IR models one logical init-style constructor callable per `ConstructorId`. Separate wrapper or init-helper symbols, if still useful, are target-lowering details below backend IR rather than backend IR callables.
- stable ID policy: callables are ordered by canonical callable ID sort order. Within one callable, registers are assigned in deterministic creation order as receiver, parameters, semantic locals, helper locals, then synthetic temporaries; the entry block is always `b0`; remaining blocks follow CFG construction order; instructions follow lowering order within each block; data blobs follow deterministic pooled first-encounter order.
- runtime call ownership: backend lowering may emit only runtime calls present in the repository runtime metadata registry. The backend IR copies registry-owned reference-argument and GC/safepoint metadata into serialized call sites; remaining effect fields stay conservative annotations until the registry owns them explicitly.
- JSON dump contract: canonical JSON uses project-root-relative paths with `/` separators when possible, preserves synthetic paths verbatim, preserves zero-based `offset` plus one-based `line` and `column`, and serializes doubles as raw IEEE-754 binary64 bits in lower-case hexadecimal rather than JSON numbers.
- phase-1 CLI contract: phase 1 freezes the CLI flag names and argument shapes for backend IR dumping and stop-after behavior, but full checked-path `--dump-backend-ir` and `--stop-after backend-ir` execution is only required once backend lowering exists in phase 2. Phase 1 may rely on fixture-only plumbing plus limited CLI validation.
- target backend interface: each target backend consumes verified backend IR plus a target options object and produces target assembly text. Targets own ABI lowering, legality, frame layout, call lowering, and emission. Shared backend analyses remain outside target packages.
- non-SSA join convention: merge copies are represented as ordinary backend instructions. When per-edge copies are required, critical edges are split and the copies live in predecessor or edge-split blocks. Backend IR v1 introduces no special edge-transfer instruction family.

## Phase 1: Establish The Backend IR Contract And Migration Seam

### Purpose

Create the new backend package, freeze the backend IR v1 shape, and add serialization/inspection tooling before any feature migration begins.

The concrete ordered implementation checklist for this phase lives in [docs/BACKEND_IR_PHASE1_IMPLEMENTATION_PLAN.md](BACKEND_IR_PHASE1_IMPLEMENTATION_PLAN.md).

### Deliverables

- `compiler/backend/` package exists with empty but stable top-level structure.
- backend IR model types are defined.
- JSON serializer and parser exist.
- human-readable text dumper exists.
- backend IR verifier exists.
- CLI flag names and argument shapes for backend IR dump and stop-after behavior are reserved behind non-default flags, even if full checked-path execution is deferred until phase 2.
- current legacy backend path remains the default and only production path.

### Key Work In This Phase

- Implement the frozen backend IR data model.
- Implement canonical JSON schema and versioning.
- Implement deterministic stable ID assignment rules.
- Implement the shared target backend interface scaffold that later `x86-64 SysV` and `aarch64` backends will satisfy.

### Test Plan

Add focused tests under new paths such as:

- `tests/compiler/backend/ir/test_model.py`
- `tests/compiler/backend/ir/test_serialize.py`
- `tests/compiler/backend/ir/test_text.py`
- `tests/compiler/backend/ir/test_verify.py`
- `tests/compiler/integration/test_cli_backend_ir_flags.py`

Concrete validation:

1. serializer round-trip tests for small programs
2. deterministic JSON/text snapshot tests
3. verifier tests for malformed CFGs, invalid operand references, missing terminators, and bad type uses
4. CLI tests for flag parsing, help text, and reserved backend IR flag behavior without requiring full checked-path lowering yet

Phase gate:

- all new backend IR unit tests pass
- legacy compiler output is unchanged when backend IR flags are not used

## Phase 2: Lower Linked Semantic Programs To Backend IR CFG

### Purpose

Build a complete lowering path from `LinkedSemanticProgram` into backend IR without changing the production assembly path yet.

The concrete ordered implementation checklist for this phase lives in [docs/BACKEND_IR_PHASE2_IMPLEMENTATION_PLAN.md](BACKEND_IR_PHASE2_IMPLEMENTATION_PLAN.md).

### Deliverables

- backend IR lowering entrypoint exists
- functions, methods, and constructors lower to CFG basic blocks
- semantic locals lower to backend virtual registers
- explicit terminators replace structured control flow
- spans and source locations are preserved on blocks/instructions
- call/dispatch forms are represented in backend IR
- full checked-path `--dump-backend-ir` and `--stop-after backend-ir` behavior exists once backend lowering is wired

### Scope Notes

This phase should consume `LinkedSemanticProgram` directly.

That keeps the semantic/backend boundary stable during the transition. The semantic IR remains semantic. The backend IR becomes the new execution-oriented representation.

The existing executable/lowered semantic form may remain temporarily as the legacy backend input during migration, but it is no longer the planned source form for the new backend path.

### Key Decisions In This Phase

- how current helper locals map to backend virtual registers
- how `if`, `while`, and lowered `for in` forms become CFG blocks
- how calls, dispatches, casts, array operations, and runtime-backed operations appear in backend IR
- how source-level constructor flows lower into the chosen single-callable init-style constructor representation

### Test Plan

Add focused lowering tests such as:

- `tests/compiler/backend/lowering/test_basics.py`
- `tests/compiler/backend/lowering/test_control_flow.py`
- `tests/compiler/backend/lowering/test_backend_calls.py`
- `tests/compiler/backend/lowering/test_arrays.py`
- `tests/compiler/backend/lowering/test_objects.py`
- `tests/compiler/integration/test_cli_backend_ir_dump.py`

Concrete validation:

1. IR text snapshot tests for representative programs:
   - arithmetic
   - branches
   - loops
   - `for in`
   - function/static/instance/interface/virtual calls
   - constructors
   - arrays and slices
   - casts and type tests
2. verifier runs over every lowered fixture
3. cross-check that all current function-like bodies lower to valid backend IR
4. CLI integration tests for `--dump-backend-ir` and `--stop-after backend-ir` once lowering is wired

Phase gate:

- representative semantic fixtures lower to valid backend IR
- IR dumps are stable and readable
- no production asm path has changed yet

## Phase 3: Move Correctness-Critical Backend Analyses Onto Backend IR

### Purpose

Replace the current tree-walking backend analyses with CFG-based backend IR analyses.

This is the phase that removes the largest architectural risk in the current backend.

### Deliverables

- CFG indexing utilities
- unreachable block elimination
- basic CFG simplification
- virtual-register liveness analysis
- safepoint/reference liveness analysis
- named root slot planning based on backend IR liveness
- stack-home planning for backend virtual registers and temporaries
- deterministic block ordering for target emission

### Scope Notes

This phase should intentionally replace the logic currently embedded in the legacy backend's layout and root-liveness tree walks.

The new analyses should become the correctness source of truth for the new backend path.

### Key Decisions In This Phase

- representation of live sets for mutable virtual registers
- representation of safepoint summaries for GC-root planning
- how reference-typed virtual registers map to named root slots
- whether trivial copy elimination runs before or after liveness
- whether empty/jump-only blocks are simplified before block ordering

### Test Plan

Add focused analysis tests such as:

- `tests/compiler/backend/analysis/test_cfg.py`
- `tests/compiler/backend/analysis/test_simplify_cfg.py`
- `tests/compiler/backend/analysis/test_liveness.py`
- `tests/compiler/backend/analysis/test_safepoints.py`
- `tests/compiler/backend/analysis/test_root_slots.py`
- `tests/compiler/backend/analysis/test_stack_homes.py`

Concrete validation:

1. branch and loop liveness tests
2. loop-carried reference/root tests that cover the current loop-clearing failure mode
3. safepoint live-set tests for nested calls, array operations, and dispatch calls
4. root-slot reuse tests over non-overlapping lifetimes
5. stack-home planning tests for calls, temporaries, doubles, and mixed control flow

Regression coverage to port or mirror:

- current root liveness cases
- current root slot plan cases
- current layout corner cases

Phase gate:

- backend IR analyses cover the current root-liveness/layout correctness surface
- loop-carried reference tests pass without the legacy loop-clearing workaround

## Phase 4: Bring Up The New `x86-64 SysV` Backend On A Reduced Feature Slice

### Purpose

Prove the end-to-end backend IR path by emitting real `x86-64 SysV` assembly for a smaller feature slice before broadening to full parity.

### Deliverables

- target backend package `compiler/backend/targets/x86_64_sysv/`
- explicit ABI descriptor for `x86-64 SysV`
- backend IR to assembly emission for:
  - integer arithmetic
  - boolean/comparison logic
  - branches and loops
  - direct calls
  - returns
  - basic function prologue/epilogue
- stack-backed virtual-register emission strategy

### Scope Notes

This phase should not attempt full language parity yet.

The goal is to prove:

- the backend IR is sufficient
- the target backend boundary is viable
- assembly emission no longer depends on the legacy statement/expression tree emitters

### Test Plan

Add focused target tests such as:

- `tests/compiler/backend/targets/x86_64_sysv/test_abi.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`

Concrete validation:

1. assembly text tests for small functions and branches
2. execution tests for arithmetic and direct-call samples
3. filtered golden runs covering:
   - arithmetic
   - basic control flow
   - simple function calls

Recommended commands for the phase gate:

```text
pytest tests/compiler/backend/targets/x86_64_sysv -q
./scripts/golden.sh --filter 'arithmetic/**'
```

Phase gate:

- reduced-scope golden slice passes on the new backend path
- legacy backend remains available for unsupported features

## Phase 5: Reach Full Feature Parity On The New Backend Path

### Purpose

Complete the `x86-64 SysV` backend so the new backend IR path covers the current supported language/runtime surface.

### Deliverables

- full support for:
  - doubles and mixed call signatures
  - constructors and constructor init helpers
  - instance/static/virtual/interface dispatch
  - arrays, slices, and lowered `for in`
  - strings and string helper flows
  - casts and type tests
  - object and interface metadata usage
  - externs, exports, and entrypoint handling
  - runtime trace hooks
  - GC root frame setup and teardown
- global backend context owns class hierarchy and metadata preparation for the new backend path
- the new backend path can compile the same supported programs as the legacy backend path

### Scope Notes

This phase is still correctness-focused.

No attempt should be made to add register allocation or backend optimization beyond what is necessary to keep the emitted assembly correct and maintainable.

### Test Plan

Add or migrate focused tests such as:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_metadata.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_strings.py`

Concrete validation:

1. port current backend unit coverage to the new backend path
2. add targeted execution/integration tests for constructors, arrays, interfaces, and casts
3. run filtered golden suites by feature family:
   - arrays
   - objects
   - interfaces
   - stdlib-heavy samples
4. run runtime harnesses because the new backend path directly exercises the runtime ABI and GC protocol

Recommended commands for the phase gate:

```text
pytest tests/compiler/backend tests/compiler/integration -q
./scripts/golden.sh
make -C runtime test-all
```

Phase gate:

- full golden suite passes on the new backend path
- runtime harnesses pass
- legacy backend is still available, but the new backend is feature-complete

## Phase 6: Cut Over Fully And Remove The Legacy Backend Path

### Purpose

Make backend IR the only backend input and remove the legacy tree-to-assembly backend path.

### Deliverables

- default checked CLI path uses backend IR plus the new `x86-64 SysV` backend
- legacy statement/expression emitters are removed or retired
- legacy layout/root-liveness tree analyses are removed from production use
- dump/inspection hooks for backend IR remain supported
- docs are updated so backend IR is the canonical backend seam

### Scope Notes

This phase should happen only after the new backend path is already passing the full suite.

Cleanup should not begin until the parity gate from phase 5 is met.

### Test Plan

Concrete validation:

1. full compiler pytest suite
2. full golden suite
3. full runtime harness suite
4. CLI integration tests for backend IR dumps and stop-after flags
5. targeted regression tests that ensure old loop-root-clearing behavior is no longer depended upon

Recommended commands for the phase gate:

```text
pytest -q
./scripts/golden.sh
make -C runtime test-all
./scripts/test.sh
```

Phase gate:

- all existing checked-path tests pass with backend IR as the only backend input
- the full golden suite passes
- backend IR dumps remain stable and usable for debugging

## Test Strategy Across All Phases

The transition should use three layers of validation throughout:

### 1. Structural Tests

These validate the IR and its analyses directly.

Examples:

- serializer round-trips
- verifier failures on malformed IR
- CFG and liveness snapshots
- root-slot and stack-home planning fixtures

### 2. Backend Unit Tests

These validate `x86-64 SysV` emission without depending only on whole-program golden tests.

Examples:

- prologue/epilogue shape
- call lowering
- block labels and branch layout
- metadata sections
- runtime root frame mechanics

### 3. End-To-End Tests

These validate that the compiler still behaves correctly for real programs.

Required end-to-end validation:

- targeted integration tests
- filtered golden runs during bring-up
- full golden suite before cutover
- runtime harness suite before and after cutover

## Exit Criteria For This Plan

This transition is complete when all of the following are true:

1. The checked backend path lowers through backend IR.
2. The backend IR is the only backend input.
3. The backend IR is serializable to stable JSON and stable text form.
4. The `x86-64 SysV` backend is fully driven by backend IR and backend analyses, not legacy tree emitters.
5. The current full golden suite passes.
6. Runtime harnesses pass.
7. The design remains ready for a future `aarch64` backend and a later SSA transition.

## Deferred Follow-On Work

After this transition lands, the next major follow-on topics should be tracked in separate documents:

- SSA construction and SSA-based optimization plan
- performance parity and register allocation plan
- `aarch64` backend plan
- target-neutral optimization pass roadmap

Those are deliberately not part of this first transition document.