# Backend IR Phase 5 Implementation Plan

Status: in progress.

This document expands phase 5 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 5 work only:

- expanding the reduced `x86-64 SysV` backend IR path to full feature parity with the current checked backend surface
- moving program-global metadata preparation onto the new backend path
- completing target lowering for objects, arrays, strings, dispatch, casts, runtime hooks, and GC root handling
- validating the new backend path across integration tests, golden suites, and runtime harnesses while keeping the legacy backend available

It does not include changing the default checked backend to the new path, removing the legacy backend, introducing register allocation, or adding target-independent optimization work.

## Implementation Rules

Use these rules for every phase-5 patch:

1. Build on the explicit phase-4 target backend rather than reopening legacy statement or expression emitters. New behavior should flow from verified backend IR plus phase-3 analyses.
2. Keep the new backend path behind the explicit non-default selector introduced in phase 4. Phase 5 may widen what that selector supports, but the default checked backend must remain the legacy path until phase 6.
3. Move program-global work into explicit backend context modules. Class hierarchy indexing, symbol naming, metadata records, interface slot layout, and string pooling should not be rediscovered ad hoc inside per-callable emitters.
4. Preserve the phase-3 ownership boundary: stack homes, root slots, block order, and safepoint summaries come from the backend IR pipeline and are consumed by the target backend rather than recomputed locally.
5. Keep unsupported shapes explicit while parity is still incomplete. Each slice should either implement a feature family end to end or continue to fail deterministically with a readable limitation message.
6. Preserve deterministic output everywhere: metadata order, symbol order, type record order, string-blob order, frame-slot order, helper-label order, and emitted assembly text must be stable across runs.
7. Reuse the current codegen package only as a migration reference for correctness surfaces, ABI details, and expected assembly patterns. Do not bridge back through `compiler/codegen/` for production backend decisions.
8. Add focused target-backend tests in the same slice as the feature family they validate, then widen to integration, golden, and runtime coverage only after unit surfaces are green.
9. Keep runtime protocol work readable and explicit. GC root-frame setup, trace-hook wiring, metadata sections, and dispatch tables should each have dedicated helpers or modules rather than being folded into one large emitter.
10. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [x] PR 1: Add program-global backend context, symbols, class-hierarchy indexing, and metadata preparation for the new backend path.
2. [x] PR 2: Add full scalar ABI coverage for doubles, mixed signatures, and remaining call or return legality.
3. [x] PR 3: Implement constructors, object allocation, field access, and object-metadata-backed emission.
4. [x] PR 4: Implement arrays, slices, string flows, and lowered `for in` collection paths.
5. [x] PR 5: Implement virtual, interface, and runtime-backed dispatch plus interface metadata sections.
6. [ ] PR 6: Implement casts, type tests, runtime trace hooks, extern/export/entrypoint handling, and multimodule parity.
7. [ ] PR 7: Implement GC root-frame setup and teardown from backend root-slot analysis and run the full parity validation gate.

## PR 1: Program-Global Backend Context, Symbols, Class Hierarchy, And Metadata Preparation

### Goal

Move the remaining program-global backend preparation responsibilities onto explicit backend modules so the new target backend no longer depends on legacy codegen metadata discovery.

This slice should establish one backend-global context object that target emitters can consume alongside per-callable backend IR pipeline results.

### Primary Files To Change

New files:

- `compiler/backend/program/symbols.py`
- `compiler/backend/program/class_hierarchy.py`
- `compiler/backend/program/metadata.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_metadata.py`

Existing files:

- `compiler/backend/program/__init__.py`
- `compiler/backend/targets/api.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`
- `compiler/codegen/symbols.py` as a migration reference for mangling and label-shape behavior only
- `compiler/codegen/class_hierarchy.py` as a migration reference for hierarchy indexing only
- `compiler/codegen/metadata.py` as a migration reference for record-layout and emission order only
- `tests/compiler/codegen/test_symbols.py` and `tests/compiler/codegen/test_emit_asm_casts_metadata.py` as migration-reference coverage only

### What To Change

1. Add explicit backend-global context modules under `compiler/backend/program/`.
   The minimum surface should cover:
   - canonical symbol naming for functions, methods, constructors, runtime helpers, and metadata labels
   - class hierarchy indexing needed by casts, type tests, and dispatch
   - prepared metadata records for classes, interfaces, slot tables, and pooled strings

2. Define one concrete backend-global context object consumed by the target backend.
   The context should be built once per program and should own deterministic order for:
   - classes and interfaces
   - metadata records and tables
   - string blobs
   - helper symbols or section labels

3. Keep metadata preparation separate from assembly printing.
   `metadata.py` should build structured records and layout decisions; target emission should only format them into assembly sections.

4. Preserve the legacy observable symbol contract where required for parity.
   If existing integration tests or runtime harnesses depend on specific exported label shapes, the backend-global symbol layer should reproduce those shapes intentionally rather than incidentally.

5. Thread the backend-global context into the target entrypoint.
   The `x86_64_sysv` emitter should consume both:
   - the verified backend program plus phase-3 analyses
   - the prepared backend-global context

### What To Test

1. Symbol generation is deterministic and matches the expected callable, metadata, and epilogue label contracts.
2. Class hierarchy and interface-layout preparation preserve deterministic order across runs.
3. Metadata preparation creates the expected records for representative classes and interfaces.
4. Prepared metadata order is stable for multimodule programs.
5. The target backend can consume the backend-global context without re-querying legacy codegen helpers.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_metadata.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_metadata.py tests/compiler/backend/ir tests/compiler/backend/lowering tests/compiler/integration/test_cli_multimodule_codegen.py -q
```

### Expected Outcome

- The new backend path owns its own symbol and metadata preparation.
- Per-callable emitters no longer need to rediscover class or interface metadata on demand.
- Later phase-5 slices can emit objects, dispatch, and strings through one deterministic global context.

### Checklist

- [x] Add `compiler/backend/program/symbols.py`, `class_hierarchy.py`, and `metadata.py`.
- [x] Define one deterministic backend-global context object.
- [x] Preserve required symbol and metadata label contracts.
- [x] Thread the global context into the target backend.
- [x] Add focused metadata and symbol coverage.

## PR 2: Doubles, Mixed Signatures, And Full Scalar ABI Coverage

### Goal

Extend the phase-4 reduced scalar backend to the full scalar ABI surface, including `double` values and mixed integer or floating-point call signatures.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/codegen/ops_float.py` as a migration reference for floating-point instruction shapes only
- `compiler/codegen/test_emit_asm_calls.py` and `compiler/codegen/test_emit_asm_int_ops.py` as migration references for mixed-signature and scalar-call coverage only

### What To Change

1. Expand the SysV ABI descriptor to include floating-point argument and return paths.
   Cover at least:
   - `xmm` argument registers for `double`
   - `xmm0` return-value handling
   - mixed integer and floating-point parameter ordering rules
   - stack-passed overflow arguments for mixed signatures

2. Add floating-point instruction selection for backend IR operations already present in the lowered program surface.
   Cover:
   - `double` constants
   - arithmetic and comparison operations
   - moves between stack homes and `xmm` scratch registers
   - cast sequences required within the full scalar slice if they are already represented in backend IR

3. Keep scratch-register policy explicit for both GPR and `xmm` paths.
   Document which scratch registers are available for:
   - integer sequences
   - floating-point sequences
   - mixed comparison or move sequences

4. Preserve deterministic legality errors for still-unsupported non-scalar features.
   This slice should widen scalar support only; it should not silently start accepting object or dispatch-heavy programs without the later slices.

### What To Test

1. `double` constants, arithmetic, and comparisons emit deterministic assembly.
2. Mixed integer or floating-point call signatures place arguments in the expected SysV registers and stack slots.
3. `double` return values flow through the correct ABI register.
4. Repeated emission of mixed-signature programs is byte-for-byte stable.
5. Scalar floating-point samples execute correctly through the new backend path.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py tests/compiler/backend/lowering/test_backend_calls.py -q
```

### Expected Outcome

- The new backend covers the full scalar ABI surface needed for parity.
- Mixed integer and floating-point call paths are explicit and testable.
- Later object, array, and dispatch slices can build on a complete scalar foundation instead of special-casing doubles separately.

### Checklist

- [x] Extend the SysV ABI module for floating-point and mixed-signature calls.
- [x] Add `double` instruction selection and return handling.
- [x] Keep GPR and `xmm` scratch-register policy explicit.
- [x] Preserve deterministic unsupported-feature legality errors outside the scalar slice.
- [x] Add floating-point and mixed-signature coverage.

## PR 3: Constructors, Object Allocation, Field Access, And Object Metadata Emission

### Goal

Bring up object-oriented code generation on the new backend path, including constructor callables, object allocation, field loads or stores, and the metadata sections those paths depend on.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py`

Existing files:

- `compiler/backend/program/metadata.py`
- `compiler/backend/program/class_hierarchy.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/codegen/test_emit_asm_objects.py` as migration-reference coverage only
- `compiler/codegen/test_emit_asm_casts_metadata.py` as migration-reference coverage for class metadata layout only

### What To Change

1. Add object-allocation lowering from backend IR allocation instructions to the target backend.
   That includes:
   - metadata or type-record address materialization
   - constructor-callable label handling where needed
   - deterministic storage of the allocated result into stack homes or ABI registers

2. Implement constructor callables end to end.
   Cover:
   - receiver-aware constructor entry or return shape
   - constructor-local frame planning
   - constructor-call lowering from ordinary call sites

3. Implement field load and field store emission.
   Field-address computation should come from prepared metadata or field layout data, not from ad hoc emitter-side inference.

4. Keep object metadata ownership in the backend-global context.
   The target emitter should read prepared type or field-layout records rather than rebuilding them per callable.

5. Preserve deterministic failure for not-yet-implemented dispatch families.
   This slice should cover objects and constructors, but virtual or interface dispatch should still fail clearly until PR 5 lands.

### What To Test

1. Constructor callables and constructor call sites emit deterministic assembly.
2. Object allocation and field access use the expected metadata or offset records.
3. Constructor receiver flow is correct for initialization-heavy samples.
4. Object-heavy samples execute correctly through the new backend path.
5. Metadata and object-section ordering remain deterministic in multimodule programs.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_metadata.py tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py tests/compiler/backend/lowering/test_objects.py tests/compiler/integration/test_cli_multimodule_codegen.py -q
```

### Expected Outcome

- The new backend can compile constructor and object-heavy programs without relying on legacy object emitters.
- Field access and object metadata come from one explicit backend-global source.
- The object model is now in place for later casts and dispatch slices.

### Checklist

- [x] Implement object allocation lowering from backend IR.
- [x] Implement constructor callable and constructor call-site emission.
- [x] Implement field load and field store emission from prepared layout metadata.
- [x] Preserve clear failures for still-missing dispatch families.
- [x] Add focused object and constructor coverage.

## PR 4: Arrays, Slices, String Flows, And Lowered `for in` Collection Paths

### Goal

Bring array and string-heavy runtime-backed operations onto the new backend path, including lowered `for in` collection loops and string helper flows that depend on runtime calls or pooled data.

### Primary Files To Change

New files:

- `compiler/backend/targets/x86_64_sysv/array_runtime.py`
- `compiler/backend/targets/x86_64_sysv/array_codegen.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_strings.py`

Existing files:

- `compiler/backend/program/metadata.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/codegen/abi/runtime.py` as a migration reference for runtime-call ownership and reference-argument metadata only
- `compiler/codegen/test_emit_asm_arrays.py` and `compiler/codegen/test_emit_asm_strings.py` as migration-reference coverage only
- `tests/compiler/backend/lowering/test_arrays.py` as source-fixture guidance only

### What To Change

1. Implement runtime-backed array operations on the new backend path.
   Cover the feature families already present in backend IR:
   - array allocation
   - array length
   - element load and store
   - slice load and slice store
   - bounds and null checks as required by the lowered backend IR surface

2. Implement lowered `for in` collection paths end to end.
   Cover both:
   - array-direct iteration fast paths already represented in backend IR
   - runtime-backed or helper-call iteration paths emitted by lowering

3. Implement string and string-helper flows.
   Cover at least:
   - pooled string data blobs
   - backend IR references to string bytes or helper calls
   - target emission of the required readonly data or helper labels

4. Keep runtime call ownership explicit.
   Runtime-call lowering should rely on backend IR call-target metadata and the runtime registry surface rather than hardcoded emitter-side guesses about GC or reference arguments.

5. Preserve deterministic failure for not-yet-landed dispatch or cast families.
   This slice should widen collection and string support only.

### What To Test

1. Array allocation, indexing, slicing, and length operations emit deterministic assembly.
2. Lowered `for in` loops compile through both direct and helper-backed collection paths.
3. String literals and helper flows emit deterministic data sections and call sequences.
4. Array-heavy and string-heavy samples execute correctly through the new backend path.
5. Runtime-call sequences preserve expected argument ordering and alignment behavior.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_strings.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py tests/compiler/backend/targets/x86_64_sysv/test_strings.py tests/compiler/backend/lowering/test_arrays.py tests/compiler/integration/test_cli_multimodule_codegen.py -q
```

### Expected Outcome

- The new backend handles array, slice, string, and lowered `for in` workloads through explicit backend IR lowering.
- Runtime-backed collection flows no longer depend on legacy array or string emitters.
- Collection and string parity are in place for the final dispatch and root-runtime slices.

### Checklist

- [x] Implement runtime-backed array and slice emission.
- [x] Implement lowered `for in` collection paths.
- [x] Implement string data and helper-call flows.
- [x] Keep runtime call ownership driven by backend IR metadata.
- [x] Add focused array, slice, `for in`, and string coverage.

## PR 5: Virtual, Interface, And Runtime-Backed Dispatch Plus Interface Metadata Sections

### Goal

Complete the dispatch surface on the new backend path by implementing instance, virtual, interface, and runtime-backed dispatch flows together with the metadata sections they consume.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py`

Existing files:

- `compiler/backend/program/metadata.py`
- `compiler/backend/program/class_hierarchy.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/asm.py`
- `compiler/codegen/test_emit_asm_objects.py` and `compiler/codegen/test_emit_asm_casts_metadata.py` as migration-reference coverage only
- `tests/compiler/backend/lowering/test_backend_calls.py` and `tests/compiler/backend/lowering/test_objects.py` as source-fixture guidance only

### What To Change

1. Implement receiver-aware non-static call lowering on the new backend path.
   Cover:
   - direct instance-method calls when the target is already concrete
   - virtual dispatch through prepared slot metadata
   - interface dispatch through prepared interface tables or slot structures

2. Emit the interface and virtual metadata sections consumed by dispatch.
   Metadata ownership should stay in the backend-global context, with target emission only formatting the prepared tables.

3. Implement runtime-backed dispatch calls still represented explicitly in backend IR.
   This includes helper-backed collection or cast-related calls that are not plain direct function calls.

4. Preserve null-check and dispatch semantics.
   Dispatch lowering must preserve the observable runtime behavior of nullable receivers and method-call failure surfaces expected by existing tests.

5. Keep dispatch-family lowering explicit and reviewable.
   Prefer dedicated helpers for each call-target family over one giant conditional inside the main emitter.

### What To Test

1. Direct instance-method calls, virtual calls, and interface calls emit deterministic assembly.
2. Dispatch metadata sections appear in deterministic order and contain the expected labels or slots.
3. Nullable receiver dispatch behavior matches the legacy checked backend surface.
4. Dispatch-heavy samples execute correctly through the new backend path.
5. Multimodule interface and virtual-call programs retain stable symbol and metadata ordering.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_metadata.py tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py tests/compiler/backend/lowering/test_backend_calls.py tests/compiler/integration/test_cli_multimodule_codegen.py -q
```

### Expected Outcome

- The new backend supports the full call-target family required for parity.
- Interface and virtual metadata are emitted from the backend-global context rather than legacy codegen tables.
- Dispatch semantics now match the observable legacy backend surface for supported programs.

### Checklist

- [x] Implement direct instance, virtual, and interface dispatch lowering.
- [x] Emit deterministic interface and virtual metadata sections.
- [x] Implement runtime-backed non-direct call families still present in backend IR.
- [x] Preserve nullable receiver and dispatch failure semantics.
- [x] Add focused dispatch and metadata coverage.

## PR 6: Casts, Type Tests, Runtime Trace Hooks, Extern, Export, And Entrypoint Handling, And Multimodule Parity

### Goal

Close the remaining feature gaps outside GC root mechanics by implementing casts, type tests, runtime trace hooks, symbol visibility handling, and multimodule checked-path parity on the new backend path.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py`

Existing files:

- `compiler/backend/program/symbols.py`
- `compiler/backend/program/metadata.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/asm.py`
- `compiler/cli.py`
- `tests/compiler/integration/test_cli_codegen.py`
- `tests/compiler/integration/test_cli_multimodule_codegen.py`
- `tests/compiler/integration/test_cli_logging.py`
- `compiler/codegen/test_emit_asm_casts_metadata.py` and `compiler/codegen/test_emit_asm_strings.py` as migration-reference coverage only

### What To Change

1. Implement remaining cast and type-test lowering families on the new backend path.
   Cover:
   - primitive casts in the now-complete scalar surface
   - class and interface checked casts
   - class and interface type tests
   - runtime-helper-backed cast or test paths where required

2. Implement runtime trace-hook wiring under target options.
   The new backend should honor the same checked-path runtime-trace toggles as the legacy backend, including deterministic omission when tracing is disabled.

3. Complete extern, export, and entrypoint handling.
   Cover:
   - exported symbol visibility and label shape
   - extern-call lowering through the target ABI layer
   - correct `main` entrypoint behavior on the explicit new backend selector

4. Re-run multimodule symbol and metadata behavior through the new backend path.
   The backend-global symbol and metadata layers should now own multimodule ordering and visibility behavior directly.

5. Keep the default checked backend unchanged.
   This slice may broaden the explicit new-backend selector to most or all language features except any remaining GC-root gaps, but it must not change the selector-less path.

### What To Test

1. Casts and type tests emit deterministic assembly and preserve expected runtime behavior.
2. Runtime trace hooks are emitted or omitted according to target options.
3. Exported symbols, extern calls, and entrypoint handling match the legacy observable surface.
4. Multimodule programs compile and run correctly through the explicit new backend selector.
5. Existing CLI logging and checked-path behavior remain stable when the selector is absent.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py -q
pytest tests/compiler/integration/test_cli_multimodule_codegen.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_multimodule_codegen.py tests/compiler/integration/test_cli_logging.py tests/compiler/integration/test_cli_errors.py -q
```

### Expected Outcome

- The new backend covers casts, type tests, runtime tracing, externs, exports, and multimodule entry behavior.
- Most observable checked-path program behavior now matches the legacy backend under the explicit selector.
- The only remaining parity gap should be GC root-frame correctness and the final parity gate.

### Checklist

- [ ] Implement remaining cast and type-test families.
- [ ] Implement runtime trace-hook wiring under target options.
- [ ] Complete extern, export, and entrypoint handling.
- [ ] Validate multimodule parity through the explicit new backend selector.
- [ ] Re-run CLI coverage to prove the default backend remains unchanged.

## PR 7: GC Root Frames, Root-Slot Synchronization, And Full Parity Validation Gate

### Goal

Finish correctness-critical runtime support by wiring phase-3 root-slot analysis into the target backend’s GC root-frame setup and teardown, then run the full parity validation gate for the explicit new backend path.

### Primary Files To Change

New files:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/analysis/root_slots.py` only if a tiny target-consumption helper extraction improves readability without changing the phase-3 contract
- `compiler/cli.py`
- `scripts/build.sh`
- `scripts/run.sh`
- `scripts/golden.sh`
- `tests/compiler/integration/helpers.py`
- `tests/compiler/integration/test_cli_codegen.py`
- `tests/compiler/integration/test_cli_errors.py`
- `compiler/codegen/test_emit_asm_runtime_roots.py` as migration-reference coverage only

### What To Change

1. Implement root-frame setup and teardown from backend root-slot analysis.
   Cover at least:
   - deterministic root-slot storage locations in the concrete frame layout
   - prologue setup for callables with safepoints and rooted references
   - epilogue teardown
   - synchronization of live rooted values before safepoints and calls that may GC

2. Consume phase-3 safepoint and root-slot analysis directly.
   The target backend should rely on the backend pipeline result rather than re-running legacy root-liveness logic or statement-tree dead-root clearing.

3. Preserve loop-carried and continuation-facing root correctness.
   Root synchronization should respect the phase-3 safepoint model and should not recreate the old loop-clearing workaround in target-specific form.

4. Broaden the explicit new backend selector to the full supported feature surface.
   Programs that were previously rejected only because root-frame support was missing should now compile or run under the explicit new backend path.

5. Run the full phase-5 validation gate.
   This slice is not complete until the explicit new backend path passes:
   - focused target-backend tests
   - backend and integration pytest coverage
   - full golden coverage
   - runtime harnesses

### What To Test

1. Root-frame prologue and epilogue sequences emit correctly for functions with safepoints.
2. Root-slot synchronization keeps live references valid across calls, loops, constructors, arrays, and dispatch-heavy fixtures.
3. Loop-carried reference regressions remain fixed on the new backend path.
4. Full golden coverage passes under the explicit new backend selector.
5. Runtime harnesses pass while exercising the new backend path.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
```

Recommended parity gate commands:

```text
pytest -n auto --dist loadfile tests/compiler/backend tests/compiler/integration -q
./scripts/golden.sh -- --experimental-backend backend-ir-x86_64_sysv
make -C runtime test-all
```

### Expected Outcome

- The explicit new backend selector is now feature-complete for the current supported language surface.
- GC root correctness comes from backend IR safepoint and root-slot analysis rather than legacy tree-walk workarounds.
- Full parity validation passes while the legacy backend still remains available.

### Checklist

- [ ] Implement GC root-frame setup and teardown from backend root-slot analysis.
- [ ] Synchronize rooted values at safepoints without reintroducing legacy loop-clearing logic.
- [ ] Broaden the explicit new backend selector to the full supported feature surface.
- [ ] Pass the full backend and integration pytest gate.
- [ ] Pass the full golden suite and runtime harnesses on the new backend path.

## Phase 5 Gate Checklist

Use this checklist when phase 5 is believed to be complete.

- [ ] The new backend path owns program-global symbols, class hierarchy, metadata preparation, and string pooling.
- [ ] The `x86-64 SysV` backend supports doubles and mixed integer or floating-point call signatures.
- [ ] Constructors, object allocation, and field access work on the new backend path.
- [ ] Arrays, slices, strings, and lowered `for in` collection paths work on the new backend path.
- [ ] Virtual, interface, and runtime-backed dispatch work on the new backend path.
- [ ] Casts, type tests, runtime trace hooks, externs, exports, and multimodule entry behavior match the legacy surface.
- [ ] GC root frames and root-slot synchronization are driven by backend IR analyses rather than legacy tree walks.
- [ ] The explicit new backend selector supports the full currently supported language surface.
- [ ] Backend and integration pytest coverage pass under the new backend path.
- [ ] The full golden suite and runtime harnesses pass while the legacy backend remains available.

Recommended phase gate commands:

```text
pytest -n auto --dist loadfile tests/compiler/backend tests/compiler/integration -q
./scripts/golden.sh -- --experimental-backend backend-ir-x86_64_sysv
make -C runtime test-all
```

Expected phase gate outcome:

- all focused `x86_64_sysv` target-backend tests pass
- integration coverage passes through the explicit new backend selector
- the full golden suite passes on the new backend path
- runtime harnesses pass while exercised alongside the new backend path
- the legacy checked backend remains available until phase 6 cutover