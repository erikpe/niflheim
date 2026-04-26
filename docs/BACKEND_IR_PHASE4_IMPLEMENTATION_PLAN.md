# Backend IR Phase 4 Implementation Plan

Status: proposed.

This document expands phase 4 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 4 work only:

- introducing the concrete `compiler/backend/targets/x86_64_sysv/` package
- defining the reduced-scope `x86-64 SysV` ABI and frame model for backend IR emission
- lowering verified backend IR plus phase-3 analyses into real assembly for a reduced scalar feature slice
- proving end-to-end code generation from backend IR without changing the default checked backend path

It does not include full language parity, GC root-frame support for the full feature surface, virtual or interface dispatch, constructor bring-up, array/object lowering, doubles, register allocation, or removal of the legacy backend path.

## Implementation Rules

Use these rules for every phase-4 patch:

1. Consume the phase-3 backend pass pipeline results directly. Do not re-derive stack homes, root slots, or block order by walking semantic IR or the legacy lowered semantic tree.
2. Keep the default checked codegen path unchanged. Phase 4 may add an explicit non-default backend selector such as `--experimental-backend backend-ir-x86_64_sysv`, but ordinary checked compilation must still use the legacy backend until phase 6.
3. Start with an intentionally narrow legality slice. Unsupported backend instructions, types, effects, and callable shapes must fail deterministically with clear diagnostics rather than silently producing wrong assembly.
4. Use the phase-3 symbolic stack homes as the source of truth for materialized virtual-register storage. Phase 4 may map them to concrete frame slots, but it must not invent a second storage identity system.
5. Preserve deterministic order everywhere: callable order, block order, label order, frame-slot order, scratch-register choice, spill order, and emitted assembly text must be stable across runs.
6. Keep target lowering explicit and readable. Prefer small helpers for frame planning, call lowering, instruction selection, and text emission over a monolithic emitter.
7. Keep the reduced feature slice scalar-first: prioritize `i64`, `u64`, and `bool` direct-call programs with branches and loops before any object, array, interface, or double support.
8. Reuse legacy codegen modules only as migration references for ABI details and assembly shape. Do not route new backend emission back through `compiler/codegen/` tree emitters for correctness decisions.
9. Add focused target-backend tests in the same slice as the emitted feature family they validate.
10. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [ ] PR 1: Add the `x86_64_sysv` target package, target entrypoint, ABI descriptor, legality checker, and assembly helpers.
2. [ ] PR 2: Implement reduced-scope frame planning, stack-home materialization, and prologue or epilogue emission.
3. [ ] PR 3: Implement straight-line scalar instruction selection and return emission.
4. [ ] PR 4: Implement branch, loop, label, and block-layout emission.
5. [ ] PR 5: Implement direct-call lowering for the reduced SysV scalar slice.
6. [ ] PR 6: Wire an explicit non-default checked-path backend selector, add reduced-path integration coverage, and run the reduced golden gate.

## PR 1: Target Package, ABI Descriptor, Legality Checker, And Assembly Helpers

### Goal

Create the concrete `x86-64 SysV` target package and freeze the reduced-scope target boundary before instruction selection begins.

This slice should establish one explicit backend target entrypoint, one ABI description for the scalar subset, one legality checker for unsupported backend IR shapes, and one deterministic assembly-text helper layer.

### Primary Files To Change

New files:

- `compiler/backend/targets/x86_64_sysv/__init__.py`
- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/asm.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `tests/compiler/backend/targets/x86_64_sysv/helpers.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_abi.py`

Existing files:

- `compiler/backend/targets/api.py`
- `compiler/backend/analysis/pipeline.py` only if the target entrypoint needs a narrower typed result adapter than the current pipeline result object
- `compiler/backend/__init__.py` only if exporting the new target entrypoint improves test ergonomics cleanly
- `compiler/codegen/abi/` as a migration reference for SysV register and stack-alignment details only
- `compiler/codegen/asm.py` as a migration reference for low-level assembly text helpers only

### What To Change

1. Add the concrete target package under `compiler/backend/targets/x86_64_sysv/`.
   The minimum public surface for this phase should be one explicit assembly entrypoint, for example:

   ```python
   emit_x86_64_sysv_asm(pipeline_result, *, options: BackendTargetOptions) -> BackendEmitResult
   ```

2. Tighten the shared target interface if needed.
   `compiler/backend/targets/api.py` currently accepts an opaque verified program object. Phase 4 should make the input explicit enough that the target can consume:
   - the verified backend program
   - per-callable phase-3 analysis results
   - target options such as runtime-trace toggles or debug comments

3. Define the reduced-scope SysV ABI contract in `abi.py`.
   Cover only the phase-4 slice:
   - integer-like argument registers
   - integer-like return registers
   - caller-saved and callee-saved sets used by the emitter
   - stack-alignment rules at call boundaries
   - the reduced set of supported backend scalar types for this phase

4. Add a legality checker before real emission starts.
   It should reject unsupported backend program shapes with deterministic diagnostics, including at least:
   - doubles
   - object or array allocation and access instructions
   - virtual, interface, indirect, and runtime-dispatch calls
   - constructors and receiver-aware bodies if the implementation cannot yet emit them correctly
   - callables whose phase-3 analysis implies GC root-slot setup for this reduced slice

5. Add assembly-text helpers in `asm.py`.
   These helpers should centralize:
   - instruction formatting
   - label formatting
   - indentation rules
   - blank-line policy
   - stable directive or section rendering used by tests

6. Keep assembly comments optional and deterministic.
   If debug comments are emitted in this phase, they should be controlled through target options and should not be required for correctness tests.

### What To Test

1. The target package exports one clear entrypoint for assembly emission.
2. The reduced ABI descriptor assigns the expected integer argument and return registers.
3. Stack-alignment constants and helper predicates are stable and correct for call sites.
4. Unsupported backend shapes fail through the legality checker with readable messages.
5. Assembly helper rendering is deterministic across repeated runs.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_abi.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_abi.py tests/compiler/backend/analysis tests/compiler/backend/ir/test_verify.py -q
```

### Expected Outcome

- The repository has a real target backend package instead of only a target protocol stub.
- The reduced `x86-64 SysV` scalar ABI is frozen in one reviewable module.
- Unsupported phase-4 backend IR shapes fail early and deterministically.
- Later slices can focus on frame and instruction lowering instead of redefining the target boundary.

### Checklist

- [ ] Add `compiler/backend/targets/x86_64_sysv/` with a public target entrypoint.
- [ ] Define the reduced-scope SysV ABI surface.
- [ ] Add a legality checker for unsupported phase-4 backend IR shapes.
- [ ] Add deterministic assembly-text helpers.
- [ ] Add focused ABI and legality coverage.

## PR 2: Frame Planning, Stack-Home Materialization, And Prologue Or Epilogue Emission

### Goal

Turn phase-3 symbolic stack homes into concrete `rbp`-relative storage and emit correct reduced-scope function prologues and epilogues.

This slice should establish the first real concrete storage mapping from backend IR analysis results to `x86-64 SysV` frame layout.

### Primary Files To Change

New files:

- `compiler/backend/targets/x86_64_sysv/frame.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/analysis/stack_homes.py` only if a tiny helper extraction makes stack-home consumption cleaner without changing the phase-3 contract
- `compiler/codegen/layout.py` as a migration reference for frame-shape expectations only
- `compiler/codegen/test_emit_asm_basics.py` as reference coverage for prologue and epilogue shape only

### What To Change

1. Add a concrete frame-layout module in `frame.py`.
   It should translate one callable's phase-3 analysis into a deterministic reduced-scope frame description, including at least:
   - ordinary stack-home slots for materialized virtual registers
   - outgoing stack-argument area if needed by the call slice
   - spill or scratch reservation if the emitter needs dedicated temporary stack space
   - total frame size aligned to the SysV call boundary requirement

2. Keep root slots explicit even if unsupported in this slice.
   If phase 4 does not yet emit GC root-frame setup, the frame planner should still inspect `root_slot_by_reg` and reject callables that need root slots rather than silently ignoring them.

3. Emit a single prologue and a single epilogue shape per callable.
   The reduced slice should already standardize:
   - function label
   - `push rbp` or equivalent frame setup
   - stack-pointer adjustment
   - shared epilogue label and restore sequence

4. Materialize backend stack homes through one lookup path.
   Every later instruction-selection helper should ask the frame layout where a register lives instead of hardcoding offsets.

5. Keep the reduced slice intentionally scalar.
   Do not add object metadata sections, shadow-stack runtime ABI calls, or callee-save orchestration for the full language surface yet.

### What To Test

1. Reduced-scope scalar callables receive deterministic frame-slot assignments from symbolic stack homes.
2. Frame size and local-slot offsets are stable across repeated runs.
3. Prologue and epilogue emission matches the expected SysV shape for small functions.
4. Callables that require unsupported root-slot setup fail cleanly.
5. Empty or trivial callables still produce a valid frame shape.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_abi.py tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py tests/compiler/backend/analysis/test_stack_homes.py -q
```

### Expected Outcome

- Phase-3 symbolic homes now lower to a concrete, deterministic SysV frame layout.
- The target backend can emit correct scalar prologues and epilogues.
- Every later emitter helper has one canonical source for home-slot locations.

### Checklist

- [ ] Add `compiler/backend/targets/x86_64_sysv/frame.py`.
- [ ] Map symbolic stack homes to deterministic frame slots.
- [ ] Emit a shared prologue and epilogue shape.
- [ ] Reject unsupported root-slot-requiring callables cleanly.
- [ ] Add focused frame and prologue or epilogue coverage.

## PR 3: Straight-Line Scalar Instruction Selection And Return Emission

### Goal

Emit real assembly for straight-line reduced-scope scalar backend IR so arithmetic-heavy functions can compile end to end without control-flow joins or calls yet.

### Primary Files To Change

New files:

- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/asm.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `compiler/codegen/ops_int.py` as a migration reference for scalar arithmetic instruction shapes only
- `compiler/codegen/test_emit_asm_basics.py` as reference coverage for return and arithmetic assembly shape only

### What To Change

1. Add reduced-scope instruction selection for straight-line scalar instructions.
   Cover at least:
   - integer and boolean constants
   - copies between virtual registers
   - integer unary operations that already exist in backend IR for the reduced slice
   - integer and boolean binary operations used by arithmetic and comparison fixtures

2. Use a small, explicit scratch-register discipline.
   Document which scratch registers are used for:
   - load from stack home
   - arithmetic or compare sequence
   - store back to stack home
   Keep the chosen set tiny and deterministic.

3. Lower reduced-scope returns through the shared epilogue path.
   Return-value emission should:
   - materialize the value into the ABI return register
   - jump to the shared epilogue label if the callable has earlier return sites

4. Keep unsupported instructions explicit.
   If a backend instruction family is not part of the reduced slice yet, fail clearly from instruction selection rather than emitting placeholder assembly.

5. Prefer readability over peephole cleverness.
   It is acceptable in this phase for simple computations to round-trip through stack homes and scratch registers if the code stays obviously correct.

### What To Test

1. Straight-line scalar functions emit deterministic assembly for constants, copies, arithmetic, and comparisons.
2. Return values land in the expected SysV return register.
3. Repeated emission of the same backend program is byte-for-byte stable.
4. Unsupported instruction families still fail clearly.
5. Small arithmetic programs can compile and execute correctly through the new backend path.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py tests/compiler/backend/lowering/test_basics.py tests/compiler/backend/analysis/test_block_order.py -q
```

### Expected Outcome

- The new target backend can emit correct assembly for straight-line scalar programs.
- Stack-backed virtual-register emission works for ordinary local computations.
- The backend IR path is now executable for a meaningful but narrow feature slice.

### Checklist

- [ ] Add reduced-scope scalar instruction selection.
- [ ] Emit deterministic load, compute, and store sequences through stack homes.
- [ ] Lower returns through the shared SysV epilogue path.
- [ ] Reject unsupported instruction families clearly.
- [ ] Add straight-line assembly and execution coverage.

## PR 4: Branch, Loop, Label, And Block-Layout Emission

### Goal

Lower phase-3 ordered backend blocks into readable, deterministic assembly for branches and loops.

This slice should prove that the new target backend consumes backend CFG shape directly rather than reconstructing structured control flow from semantic statements.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/asm.py`
- `compiler/backend/analysis/block_order.py` only if a tiny helper extraction improves deterministic target-facing block traversal without changing the phase-3 contract
- `compiler/codegen/emitter_stmt.py` as a migration reference for branch or loop assembly shape only
- `tests/compiler/backend/lowering/test_control_flow.py` as source-fixture guidance only

### What To Change

1. Emit one deterministic label per backend block.
   Labels should be derived from callable identity plus `BackendBlockId`, not from unstable debug names.

2. Consume the phase-3 ordered block sequence directly.
   The target backend should not invent a second block-ordering pass. It should treat phase-3 block order as the target-facing layout order for this phase.

3. Lower conditional branches and loops from backend terminators.
   Cover at least:
   - compare and test lowering for branch conditions
   - `jump` terminators
   - `branch` terminators
   - loop back-edges
   - shared epilogue handling for early returns

4. Keep fallthrough behavior explicit and deterministic.
   It is acceptable to emit slightly redundant jumps in this phase if that keeps block-to-label correspondence obvious and easy to review.

5. Preserve single-epilogue readability.
   Multi-return callables should still converge through one emitted epilogue label unless a clearly justified reduced-scope exception is documented in tests.

### What To Test

1. Branch-heavy callables emit stable block labels and branch instructions.
2. Loop back-edges and exit edges target the expected labels.
3. Multiple returns converge through a single epilogue label.
4. Block layout follows phase-3 deterministic block order rather than source debug names.
5. Branch and loop samples execute correctly through the new backend path.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py tests/compiler/backend/analysis/test_block_order.py tests/compiler/backend/lowering/test_control_flow.py -q
```

### Expected Outcome

- The new backend emits readable assembly from backend CFG blocks directly.
- Deterministic block ordering from phase 3 now drives real target layout.
- Reduced-scope branch and loop programs compile and run through the backend IR path.

### Checklist

- [ ] Emit deterministic block labels from backend block ids.
- [ ] Lower `jump` and `branch` terminators to real assembly control flow.
- [ ] Preserve stable block layout and single-epilogue structure.
- [ ] Add branch and loop emission coverage.
- [ ] Add reduced-scope branch and loop execution coverage.

## PR 5: Direct-Call Lowering For The Reduced SysV Scalar Slice

### Goal

Add direct internal and extern call lowering for the reduced scalar feature slice so the new backend can compile simple multi-function programs.

### Primary Files To Change

New files:

- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/codegen/emitter_fn.py` as a migration reference for call-sequence shape only
- `compiler/codegen/test_emit_asm_calls.py` as a migration reference for reduced-scope direct-call coverage only
- `tests/compiler/backend/lowering/test_backend_calls.py` as source-fixture guidance only

### What To Change

1. Add a dedicated call-lowering helper in `lower_calls.py`.
   It should handle only the reduced slice:
   - direct calls to concrete callables
   - extern direct calls where signatures are already known
   - integer-like arguments and returns only

2. Implement SysV argument placement for the reduced slice.
   Cover:
   - integer-register argument assignment
   - outgoing stack arguments beyond the register budget
   - stack alignment at each call site
   - return-value materialization from the integer return register

3. Make caller scratch and temporary behavior explicit.
   The emitter should document which registers are assumed clobbered by calls and how temporary values are preserved across the call sequence.

4. Keep reference-rooted and dispatch-heavy calls out of scope.
   If a call site would require GC root-frame correctness or non-direct dispatch, reject it with a deterministic reduced-slice diagnostic.

5. Add at least one stack-argument case.
   Reduced scope should still prove the new backend can cross the register-argument boundary correctly for simple scalar programs.

### What To Test

1. Small direct-call programs emit the expected argument moves and `call` instructions.
2. Return values flow back through the expected SysV return register.
3. Calls with more than the register-argument budget use stable outgoing stack slots.
4. Stack alignment is preserved at call boundaries.
5. Reduced-scope direct-call programs execute correctly through the new backend path.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py tests/compiler/backend/lowering/test_backend_calls.py -q
```

### Expected Outcome

- The new backend can compile reduced-scope multi-function scalar programs end to end.
- SysV direct-call lowering is explicit, deterministic, and testable.
- The backend IR path now covers the minimum call surface needed for a reduced golden slice.

### Checklist

- [ ] Add reduced-scope direct-call lowering in `lower_calls.py`.
- [ ] Implement SysV integer argument and return handling.
- [ ] Preserve stack alignment across call sites.
- [ ] Reject unsupported dispatch and GC-rooted call shapes clearly.
- [ ] Add direct-call assembly and execution coverage.

## PR 6: Explicit Non-Default Checked-Path Wiring, Integration Coverage, And Reduced Golden Gate

### Goal

Make the reduced backend IR path runnable from the checked CLI behind an explicit non-default selector so integration tests and filtered golden runs can exercise the new target backend without affecting the production default path.

### Primary Files To Change

New files:

- `tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py`

Existing files:

- `compiler/cli.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`
- `compiler/backend/targets/api.py`
- `tests/compiler/integration/helpers.py`
- `tests/compiler/integration/test_cli_codegen.py`
- `tests/compiler/integration/test_cli_errors.py`
- `scripts/build.sh`
- `scripts/run.sh`
- `scripts/golden.sh` or `tests/golden/runner.py` only if forwarding a non-default backend selector is necessary for filtered golden coverage

### What To Change

1. Add one explicit non-default backend selector to the checked CLI.
   A reasonable phase-4 shape is:

   ```text
   --experimental-backend backend-ir-x86_64_sysv
   ```

   The selector should:
   - lower to backend IR
   - run the phase-3 backend pass pipeline
   - emit assembly through the new `x86_64_sysv` backend
   - leave the default checked path unchanged when the flag is absent

2. Keep unsupported programs deterministic.
   If the reduced-scope backend is selected for a program outside the slice, the CLI should fail with a readable backend limitation message rather than silently falling back to the legacy backend.

3. Add integration helpers that compile and optionally run programs through the new backend selector.
   This should mirror the existing integration helper flow closely enough that execution tests stay easy to read.

4. Add filtered golden-driver plumbing only if needed.
   If the current `scripts/golden.sh` plumbing cannot forward compiler flags, update it in the smallest clean way necessary so a reduced backend selector can be exercised on a filtered subset.

5. Re-run existing CLI coverage that proves the legacy default still owns ordinary checked codegen.

### What To Test

1. The CLI accepts the reduced backend selector and emits assembly through the new backend path.
2. The default checked codegen path is unchanged when the selector is absent.
3. Unsupported reduced-scope programs fail with deterministic backend limitation diagnostics.
4. Reduced-scope arithmetic, branch, loop, and direct-call integration samples compile and run correctly under the new selector.
5. A filtered reduced golden slice passes through the new backend path.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/targets/x86_64_sysv -q
pytest tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

Recommended reduced golden command once the selector is plumbed through:

```text
./scripts/golden.sh --filter 'arithmetic/**' -- --experimental-backend backend-ir-x86_64_sysv
```

### Expected Outcome

- The new backend IR path is runnable end to end behind one explicit non-default checked-path selector.
- Reduced-scope integration and golden coverage exercise real backend IR code generation.
- The legacy checked backend remains the production default.

### Checklist

- [ ] Add an explicit non-default backend selector for the reduced backend IR path.
- [ ] Wire the selector through the checked CLI without changing the default backend.
- [ ] Add reduced-path integration coverage for compile and run behavior.
- [ ] Add deterministic unsupported-slice diagnostics.
- [ ] Run a filtered reduced golden gate through the new backend path.

## Phase 4 Gate Checklist

Use this checklist when phase 4 is believed to be complete.

- [ ] `compiler/backend/targets/x86_64_sysv/` exists with a stable public entrypoint.
- [ ] The reduced `x86-64 SysV` ABI contract is defined in one explicit module.
- [ ] Unsupported phase-4 backend IR shapes fail through a deterministic legality check.
- [ ] Phase-3 stack homes lower to concrete, deterministic frame slots.
- [ ] Straight-line scalar backend IR lowers to correct assembly.
- [ ] Branches and loops emit directly from backend CFG block order.
- [ ] Direct scalar calls lower with correct SysV argument, return, and alignment behavior.
- [ ] An explicit non-default checked-path selector can run the reduced backend IR path end to end.
- [ ] Reduced-scope integration tests pass through the new backend path.
- [ ] A filtered reduced golden slice passes while the default checked backend remains unchanged.

Recommended phase gate commands:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
./scripts/golden.sh --filter 'arithmetic/**' -- --experimental-backend backend-ir-x86_64_sysv
```

Expected phase gate outcome:

- reduced-scope `x86-64 SysV` backend tests pass
- arithmetic, branch, loop, and direct-call samples execute through the new backend IR path
- filtered golden coverage passes through the explicit non-default selector
- the legacy checked backend path remains unchanged when the selector is absent