# AArch64 Backend Implementation Plan

This document lays out a concrete, ordered plan for adding a real `aarch64` checked backend to Niflheim while keeping as much of the compiler and test infrastructure shared as possible.

The plan is grounded in the current repository state:

- The checked compiler path still emits through `x86_64_sysv` in [compiler/cli.py](../compiler/cli.py).
- The backend IR pipeline, analysis passes, optimizations, and program metadata builders are already target-neutral.
- The runtime ABI in [runtime/include/runtime.h](../runtime/include/runtime.h) is already C-based and host-portable.
- The pytest suite is already split into all-host emit coverage versus native-runtime suites, and ARM host skips are centralized in [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py).
- Golden tests already run through a shared runner and build scripts, but they still depend on the checked compiler default path.

## Goals

1. Add a real `aarch64` backend that lowers the existing backend IR to runnable Linux AArch64 assembly.
2. Keep backend IR, runtime ABI knowledge, symbol metadata, and host/backend selection logic shared wherever that logic is not architecture-specific.
3. Keep architecture-specific code isolated under target packages.
4. Keep the pytest suite green at every slice.
5. End with both the pytest suite and golden suite runnable on `x86_64` and `aarch64` hosts where the test category is supposed to be host-native.

## End State

After the final slice:

- `compiler/backend/targets/` exposes a real registry with `x86_64_sysv` and `aarch64`.
- `nifc --target <name>` is supported on the checked path.
- The default checked target resolves to the host-native backend when one exists.
- Shared runtime-layout constants no longer live inside the `x86_64_sysv` package.
- `tests/compiler/backend/targets/x86_64_sysv/` and `tests/compiler/backend/targets/aarch64/` are both emit-only target suites.
- Native-runtime pytest suites run on `x86_64` hosts with `x86_64_sysv` and on ARM hosts with `aarch64`.
- `./scripts/build.sh`, `./scripts/run.sh`, and `./scripts/golden.sh` work on both host architectures without architecture-specific manual steps.

## Naming Decision

This plan uses the public checked-backend name `aarch64`.

That keeps the user-facing selector simple and matches the repository's existing test-planning language. If the repository later needs ABI-distinct AArch64 targets, the registry can add aliases or more specific names without changing the overall design.

## Design Rules

1. If logic is about backend IR shape, runtime struct layout, runtime call metadata, symbol metadata, or host architecture normalization, it should not live under a concrete target package.
2. If logic is about registers, instruction syntax, calling convention, stack frame layout, relocations, or instruction selection, it should live under a concrete target package.
3. Do not enable ARM native-runtime pytest or golden coverage until the `aarch64` emit-only suite covers the full checked backend surface.
4. When a test asserts target-specific assembly text, it must pin the target explicitly instead of relying on whatever the host-native default is at that point in the migration.
5. Keep `x86_64_sysv` behavior stable while shared seams are extracted.

## Ordered Slices

1. [x] Slice 1: Introduce a shared target registry and explicit checked-path target selector.
2. [x] Slice 2: Extract shared runtime-layout and target-test scaffolding out of the `x86_64_sysv` package.
3. [x] Slice 3: Add the isolated `aarch64` package skeleton with ABI and frame-model coverage.
4. [x] Slice 4: Implement the `aarch64` scalar/call/control-flow/root-frame emission backbone.
5. [x] Slice 5: Complete `aarch64` feature parity and the full emit-only target suite.
6. [ ] Slice 6: Switch ARM hosts to the native `aarch64` checked backend and enable full pytest plus golden execution.

---

## Slice 1: Introduce A Shared Target Registry And Explicit Checked-Path Target Selector

### Purpose

Create one compiler-owned source of truth for available backend targets and host-architecture normalization, then route the checked CLI through that registry without changing the default behavior yet.

### Change / Add

- Add a shared target-registry module under `compiler/backend/targets/`, for example `compiler/backend/targets/registry.py`.
- Extend [compiler/backend/targets/__init__.py](../compiler/backend/targets/__init__.py) to export the registry API, not just the protocol types.
- Move host-architecture normalization out of [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py) into compiler-owned shared code, for example `compiler/common/architectures.py` or `compiler/backend/targets/host.py`.
- Register the existing `x86_64_sysv` backend in the new registry.
- Update [compiler/cli.py](../compiler/cli.py) so checked-path emission resolves a target object from the registry instead of importing and calling `emit_x86_64_sysv_asm(...)` directly.
- Add `--target <name>` to the checked CLI.
- Keep the default checked target unchanged in this slice: no target flag should still resolve to `x86_64_sysv`.
- Update [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py) to delegate capability data to the compiler-owned registry rather than maintaining a separate hard-coded target list.
- Update direct CLI monkeypatch tests so they patch target selection or registry resolution, not the `emit_x86_64_sysv_asm` symbol in [compiler/cli.py](../compiler/cli.py).

### Files To Change

- [compiler/cli.py](../compiler/cli.py)
- [compiler/backend/targets/__init__.py](../compiler/backend/targets/__init__.py)
- [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py)
- [tests/compiler/support/test_backend_matrix.py](../tests/compiler/support/test_backend_matrix.py)
- [tests/compiler/backend/targets/test_api.py](../tests/compiler/backend/targets/test_api.py)
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)
- [tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py](../tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py)
- [tests/compiler/integration/test_cli_backend_ir_passes.py](../tests/compiler/integration/test_cli_backend_ir_passes.py)
- [tests/compiler/integration/test_cli_backend_ir_dump.py](../tests/compiler/integration/test_cli_backend_ir_dump.py)
- [tests/compiler/integration/test_cli_logging.py](../tests/compiler/integration/test_cli_logging.py)
- [tests/compiler/integration/test_cli_errors.py](../tests/compiler/integration/test_cli_errors.py)

### Notes

- The registry entry should carry both the target object and its host-runtime capability metadata. That avoids future drift between compiler selection logic and test-suite skip logic.
- This slice should not yet register `aarch64`.

### How To Test It

Run the shared API, backend-matrix, and checked-CLI suites:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/backend/targets/test_api.py \
  tests/compiler/support/test_backend_matrix.py \
  tests/compiler/integration/test_cli_codegen.py \
  tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py \
  tests/compiler/integration/test_cli_backend_ir_passes.py \
  tests/compiler/integration/test_cli_backend_ir_dump.py \
  tests/compiler/integration/test_cli_logging.py \
  tests/compiler/integration/test_cli_errors.py -q
```

### Exit Criteria

1. `nifc` without `--target` still emits through `x86_64_sysv`.
2. `nifc --target x86_64_sysv` works and is covered by tests.
3. An unknown `--target` produces a deterministic CLI error.
4. Compiler and test capability metadata come from the same logical registry.

### Checklist

- [x] Add compiler-owned host architecture normalization.
- [x] Add compiler-owned backend target registry.
- [x] Register `x86_64_sysv` in the registry.
- [x] Route [compiler/cli.py](../compiler/cli.py) through the registry.
- [x] Add checked-path `--target` parsing and validation.
- [x] Update backend-matrix tests to use registry-backed data.
- [x] Update CLI monkeypatch tests to patch registry resolution instead of direct x86 symbols.

Validation:

- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/common/test_architectures.py tests/compiler/backend/targets/test_api.py tests/compiler/support/test_backend_matrix.py tests/compiler/support/test_runtime_harness.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py tests/compiler/integration/test_cli_backend_ir_passes.py tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_logging.py tests/compiler/integration/test_cli_errors.py -q` -> `73 passed in 3.52s`

---

## Slice 2: Extract Shared Runtime-Layout And Target-Test Scaffolding Out Of The `x86_64_sysv` Package

### Purpose

Move shared runtime ABI layout knowledge and generic target-test helpers out of the `x86_64_sysv` tree before duplicating a target package for AArch64.

### Change / Add

- Add a shared runtime-layout module, for example `compiler/backend/program/runtime_layout.py`.
- Move target-neutral constants from the x86 package into that shared module:
  - root-frame layout currently in `compiler/backend/targets/x86_64_sysv/root_runtime.py`
  - object and type metadata offsets currently in `compiler/backend/targets/x86_64_sysv/object_runtime.py`
  - array object layout and kind tags currently in `compiler/backend/targets/x86_64_sysv/array_runtime.py`
- Keep only target-local operand-formatting helpers inside concrete target packages.
- Add focused tests for the new shared runtime-layout module so the runtime ABI is asserted once at the shared seam.
- Extract generic target-test helpers from [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py) into a shared target-test support module, for example `tests/compiler/backend/targets/support.py`.
- Keep only x86-specific emit helpers in the `x86_64_sysv` helper file.

### Files To Change

- [compiler/backend/program/runtime.py](../compiler/backend/program/runtime.py) if the shared layout module should live nearby or share constants
- `compiler/backend/program/runtime_layout.py`
- [compiler/backend/targets/x86_64_sysv/root_runtime.py](../compiler/backend/targets/x86_64_sysv/root_runtime.py)
- [compiler/backend/targets/x86_64_sysv/object_runtime.py](../compiler/backend/targets/x86_64_sysv/object_runtime.py)
- [compiler/backend/targets/x86_64_sysv/array_runtime.py](../compiler/backend/targets/x86_64_sysv/array_runtime.py)
- [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py)
- `tests/compiler/backend/targets/support.py`

### Notes

- This is the slice that prevents the future `aarch64` package from copying runtime-layout constants that are not actually architecture-specific.
- Avoid over-generalizing the assembly builders here. `x86_64_sysv/asm.py` is small, and AArch64 syntax will differ materially.

### How To Test It

Run the x86 target suite plus any new shared runtime-layout tests:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/backend/test_runtime_layout.py \
  tests/compiler/backend/targets/x86_64_sysv \
  tests/compiler/backend/targets/test_api.py \
  tests/compiler/support/test_backend_matrix.py -q
```

### Exit Criteria

1. No runtime-layout constant exists only inside `x86_64_sysv` if it is really part of the shared C runtime ABI.
2. The `x86_64_sysv` target suite still passes unchanged.
3. Shared test scaffolding exists for future target suites.

### Checklist

- [x] Add a shared runtime-layout module.
- [x] Move root-frame layout constants out of `x86_64_sysv/root_runtime.py`.
- [x] Move shared object/type layout constants out of `x86_64_sysv/object_runtime.py`.
- [x] Move shared array layout constants out of `x86_64_sysv/array_runtime.py`.
- [x] Add shared tests for runtime layout offsets and tags.
- [x] Extract generic target-test helpers from the x86 helper file.

Validation:

- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/backend/test_runtime_layout.py tests/compiler/backend/targets/x86_64_sysv tests/compiler/backend/targets/test_api.py tests/compiler/support/test_backend_matrix.py -q` -> `110 passed in 4.51s`

---

## Slice 3: Add The Isolated `aarch64` Package Skeleton With ABI And Frame-Model Coverage

### Purpose

Create the new target package and lock down its public surface, ABI descriptor, and frame-planning model before deeper code generation work starts.

### Change / Add

- Add `compiler/backend/targets/aarch64/` with:
  - `__init__.py`
  - `abi.py`
  - `asm.py`
  - `frame.py`
  - `emit.py`
- Define the public target name `aarch64`.
- Implement an AArch64 ABI descriptor with:
  - integer/pointer argument registers
  - floating-point argument registers
  - return registers
  - stack alignment
  - callee-saved register set
  - outgoing stack-argument accounting
- Add a frame-layout planner for AArch64 stack homes, root slots, scratch slots, and outgoing call space.
- Add `tests/compiler/backend/targets/aarch64/` with at least:
  - `helpers.py`
  - `test_abi.py`
  - `test_suite_boundaries.py`
- Keep this package out of the user-facing registry until it can compile a meaningful smoke subset in slice 4.

### Files To Add

- `compiler/backend/targets/aarch64/__init__.py`
- `compiler/backend/targets/aarch64/abi.py`
- `compiler/backend/targets/aarch64/asm.py`
- `compiler/backend/targets/aarch64/frame.py`
- `compiler/backend/targets/aarch64/emit.py`
- `tests/compiler/backend/targets/aarch64/helpers.py`
- `tests/compiler/backend/targets/aarch64/test_abi.py`
- `tests/compiler/backend/targets/aarch64/test_suite_boundaries.py`

### Notes

- This slice is intentionally package-structure-first.
- The AArch64 asm builder can be target-local from the start.
- The suite-boundary test should mirror the x86 rule: the target tree stays emit-only and must not import native-runtime helpers.

### How To Test It

Run the new AArch64 target scaffold tests:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/backend/targets/aarch64 \
  tests/compiler/backend/targets/test_api.py -q
```

### Exit Criteria

1. The new package exists with a stable public entrypoint.
2. ABI planning and frame-layout tests pass.
3. The target tree has the same emit-only boundaries as the x86 tree.

### Checklist

- [x] Add `compiler/backend/targets/aarch64/`.
- [x] Define the public target name `aarch64`.
- [x] Implement the AArch64 ABI descriptor.
- [x] Implement the AArch64 frame-layout planner.
- [x] Add target-package surface tests.
- [x] Add an emit-only suite-boundary test for the new tree.

Validation:

- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/backend/targets/aarch64 tests/compiler/backend/targets/test_api.py -q` -> `24 passed in 2.83s`

---

## Slice 4: Implement The `aarch64` Scalar / Call / Control-Flow / Root-Frame Emission Backbone

### Purpose

Make `aarch64` capable of emitting real checked assembly for the core control-flow and call machinery that the rest of the backend relies on.

### Change / Add

- Add or fill in the core AArch64 emitter modules:
  - `instruction_selection.py`
  - `lower_calls.py`
  - `root_codegen.py`
  - `trace_codegen.py`
- Support at least:
  - integer and boolean constants
  - arithmetic and comparisons
  - block-local loads/stores
  - direct returns
  - conditional branches and jumps
  - direct calls
  - callable-value loads and indirect calls
  - stack home loads/stores
  - root-frame setup and pop
  - root-slot sync and reload around safepoints
  - runtime trace hooks controlled by `BackendTargetOptions.runtime_trace_enabled`
- Add minimal symbol and data-blob address materialization needed for this slice.
- Register `aarch64` in the compiler target registry once it can emit the smoke programs covered by this slice.
- Add explicit compile-only CLI coverage for `nifc --target aarch64`.

### Files To Add Or Change

- `compiler/backend/targets/aarch64/instruction_selection.py`
- `compiler/backend/targets/aarch64/lower_calls.py`
- `compiler/backend/targets/aarch64/root_codegen.py`
- `compiler/backend/targets/aarch64/trace_codegen.py`
- `compiler/backend/targets/aarch64/emit.py`
- [compiler/cli.py](../compiler/cli.py)
- `tests/compiler/backend/targets/aarch64/test_emit_basics.py`
- `tests/compiler/backend/targets/aarch64/test_emit_calls.py`
- `tests/compiler/backend/targets/aarch64/test_emit_control_flow.py`
- `tests/compiler/backend/targets/aarch64/test_emit_runtime_roots.py`
- `tests/compiler/integration/test_cli_aarch64_codegen.py`

### Notes

- The goal is not full language parity yet.
- The goal is a stable emission backbone that can compile simple whole programs via `--target aarch64` and exercise the major non-heap control-flow seams.

### How To Test It

Run the initial AArch64 emit-only suite and explicit-target CLI smoke coverage:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/backend/targets/aarch64/test_abi.py \
  tests/compiler/backend/targets/aarch64/test_emit_basics.py \
  tests/compiler/backend/targets/aarch64/test_emit_calls.py \
  tests/compiler/backend/targets/aarch64/test_emit_control_flow.py \
  tests/compiler/backend/targets/aarch64/test_emit_runtime_roots.py \
  tests/compiler/backend/targets/test_api.py \
  tests/compiler/support/test_backend_matrix.py \
  tests/compiler/integration/test_cli_aarch64_codegen.py -q
```

### Exit Criteria

1. `nifc --target aarch64` can compile a small checked smoke corpus.
2. Root-frame emission, trace toggling, and call lowering are covered by target tests.
3. The default target remains unchanged in this slice.

### Checklist

- [x] Implement AArch64 scalar instruction selection.
- [x] Implement AArch64 call lowering.
- [x] Implement AArch64 root-frame setup, sync, reload, and pop.
- [x] Implement AArch64 trace-hook emission.
- [x] Register `aarch64` in the compiler registry once smoke coverage passes.
- [x] Add explicit `--target aarch64` compile-only CLI tests.

Validation:

- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/backend/targets/aarch64/test_abi.py tests/compiler/backend/targets/aarch64/test_emit_basics.py tests/compiler/backend/targets/aarch64/test_emit_calls.py tests/compiler/backend/targets/aarch64/test_emit_control_flow.py tests/compiler/backend/targets/aarch64/test_emit_runtime_roots.py tests/compiler/backend/targets/test_api.py tests/compiler/support/test_backend_matrix.py tests/compiler/integration/test_cli_aarch64_codegen.py -q` -> `54 passed in 3.13s`
- [x] `/bin/python3 -m pytest -n auto --dist loadfile -q` -> `1069 passed, 66 skipped in 9.94s`

---

## Slice 5: Complete `aarch64` Feature Parity And The Full Emit-Only Target Suite

### Purpose

Finish the checked backend surface for AArch64 before any ARM-native pytest or golden suites are enabled.

### Change / Add

- Add or complete the remaining AArch64 codegen modules:
  - `array_codegen.py`
  - `cast_codegen.py`
  - `object_codegen.py`
  - any target-local operand helpers needed for object, array, and metadata access
- Support the remaining checked-path features covered by the existing x86 suite:
  - object allocation and field access
  - null checks
  - checked class casts and type tests
  - interface and virtual dispatch
  - strings and data blobs
  - doubles and mixed integer/floating calls
  - array allocation, load/store, slicing, bounds checks, and fast paths
  - type metadata, pointer-offset tables, interface tables, and class vtables
  - runtime-trace-disabled emission parity
- Audit AArch64 symbol-address materialization carefully so it works with the host C toolchain defaults used by [scripts/build.sh](../scripts/build.sh).
- Add the full parallel emit-only suite under `tests/compiler/backend/targets/aarch64/`.
- Update compile-only CLI tests that currently assume x86-specific assembly or log text so they either:
  - assert generic CLI behavior only, or
  - pass `--target x86_64_sysv` / `--target aarch64` explicitly.

### Files To Add Or Change

- `compiler/backend/targets/aarch64/array_codegen.py`
- `compiler/backend/targets/aarch64/cast_codegen.py`
- `compiler/backend/targets/aarch64/object_codegen.py`
- `compiler/backend/targets/aarch64/emit.py`
- `tests/compiler/backend/targets/aarch64/test_backend_parity.py`
- `tests/compiler/backend/targets/aarch64/test_emit_arrays.py`
- `tests/compiler/backend/targets/aarch64/test_emit_casts.py`
- `tests/compiler/backend/targets/aarch64/test_emit_dispatch.py`
- `tests/compiler/backend/targets/aarch64/test_emit_doubles.py`
- `tests/compiler/backend/targets/aarch64/test_emit_objects.py`
- `tests/compiler/backend/targets/aarch64/test_metadata.py`
- `tests/compiler/backend/targets/aarch64/test_strings.py`
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)
- [tests/compiler/integration/test_cli_logging.py](../tests/compiler/integration/test_cli_logging.py)

### Notes

- The current x86 tree is the coverage map for this slice. The AArch64 tree should mirror that breadth, not just a subset of happy paths.
- This slice is the right place to add explicit tests for AArch64 relocation-safe symbol addressing, because x86 and AArch64 will necessarily materialize metadata pointers differently.

### How To Test It

Run both target trees and the compile-only CLI suites that exercise target selection and log output:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/backend/targets/x86_64_sysv \
  tests/compiler/backend/targets/aarch64 \
  tests/compiler/integration/test_cli_codegen.py \
  tests/compiler/integration/test_cli_logging.py -q
```

On an ARM host, also build a few explicit-target executables before the default switch:

```bash
./scripts/build.sh samples/arithmetic_loop.nif build/arithmetic_loop_aarch64 -- --target aarch64
./scripts/build.sh samples/function_calls.nif build/function_calls_aarch64 -- --target aarch64
```

### Exit Criteria

1. The `aarch64` emit-only suite covers the same checked backend surface as the x86 tree.
2. `nifc --target aarch64` works for the representative language features already covered by the x86 checked path.
3. No ARM-native runtime or golden suite has been enabled yet.

### Checklist

- [x] Implement AArch64 object allocation, field access, and null-check emission.
- [x] Implement AArch64 casts and type tests.
- [x] Implement AArch64 array lowering and fast paths.
- [x] Implement AArch64 double support.
- [x] Implement AArch64 interface and virtual dispatch.
- [x] Implement AArch64 metadata, strings, and data-blob emission.
- [x] Add the full parallel AArch64 emit-only test tree.
- [x] Update compile-only CLI tests so target-specific assertions pin the target explicitly.

Validation:

- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/backend/targets/aarch64 tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_logging.py -q` -> `85 passed in 3.57s`
- [x] `/bin/python3 -m pytest -n auto --dist loadfile tests/compiler/backend/targets/x86_64_sysv tests/compiler/backend/targets/aarch64 tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_logging.py -q` -> `172 passed in 4.39s`
- [x] `./scripts/build.sh samples/arithmetic_loop.nif build/arithmetic_loop_aarch64 -- --target aarch64 && ./scripts/build.sh samples/function_calls.nif build/function_calls_aarch64 -- --target aarch64` -> built `build/arithmetic_loop_aarch64` and `build/function_calls_aarch64`
- [x] `./build/arithmetic_loop_aarch64 && ./build/function_calls_aarch64` -> succeeded with exit status 0

---

## Slice 6: Switch ARM Hosts To The Native `aarch64` Checked Backend And Enable Full Pytest Plus Golden Execution

### Purpose

Once AArch64 feature parity is in place, make ARM a first-class checked compiler host by switching the checked default to host-native target selection and enabling the native-runtime and golden suites.

### Change / Add

- Update the compiler target registry and [compiler/cli.py](../compiler/cli.py) so the checked-path default target resolves from normalized host architecture when a native backend exists:
  - `x86_64` -> `x86_64_sysv`
  - `aarch64` -> `aarch64`
- Update [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py) and [tests/compiler/support/test_backend_matrix.py](../tests/compiler/support/test_backend_matrix.py) so ARM hosts resolve `aarch64` as the native runtime backend.
- Re-run and update the shared runtime-harness tests so skip behavior disappears on ARM once `aarch64` is registered as native-runnable.
- Audit [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py) and [tests/compiler/support/runtime_execution.py](../tests/compiler/support/runtime_execution.py) to make sure they do not accidentally pin `x86_64_sysv` assumptions after the host-native default switch.
- Update [tests/compiler/integration/test_build_script.py](../tests/compiler/integration/test_build_script.py) so it covers both:
  - host-native default build/run behavior
  - explicit `--target` forwarding where target selection itself is under test
- Update [tests/compiler/test_golden_runner.py](../tests/compiler/test_golden_runner.py) if the runner needs new assertions around explicit `build_args` target forwarding or host-native behavior.
- Update user-facing docs and test-policy docs:
  - [README.md](../README.md)
  - [tests/README.md](../tests/README.md)
  - [docs/TEST_PLAN_v0.1.md](./TEST_PLAN_v0.1.md)
  - [docs/ABI_NOTES.md](./ABI_NOTES.md)

### Files To Change

- [compiler/cli.py](../compiler/cli.py)
- [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py)
- [tests/compiler/support/test_backend_matrix.py](../tests/compiler/support/test_backend_matrix.py)
- [tests/compiler/support/runtime_harness.py](../tests/compiler/support/runtime_harness.py)
- [tests/compiler/support/test_runtime_harness.py](../tests/compiler/support/test_runtime_harness.py)
- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/support/runtime_execution.py](../tests/compiler/support/runtime_execution.py)
- [tests/compiler/integration/test_build_script.py](../tests/compiler/integration/test_build_script.py)
- [tests/compiler/test_golden_runner.py](../tests/compiler/test_golden_runner.py)
- [README.md](../README.md)
- [tests/README.md](../tests/README.md)
- [docs/TEST_PLAN_v0.1.md](./TEST_PLAN_v0.1.md)
- [docs/ABI_NOTES.md](./ABI_NOTES.md)

### Notes

- This is the slice where the ARM-native pytest skips should disappear.
- Compile-fail golden tests already call the compiler directly, and run-mode golden tests already go through [scripts/build.sh](../scripts/build.sh). Once the checked default target is host-native, the golden harness should work on ARM without architecture-specific special casing.
- If [docs/ABI_NOTES.md](./ABI_NOTES.md) becomes too mixed, split the current document into one shared runtime-ABI document plus per-target calling-convention notes. The important requirement is that the shared runtime layout and both calling conventions are documented explicitly.

### How To Test It

On an ARM host:

```bash
/bin/python3 -m pytest -n auto --dist loadfile
./scripts/golden.sh
make -C runtime clean test-all
```

On an `x86_64` host, re-run a representative no-regression subset after the default-switch changes:

```bash
/bin/python3 -m pytest -n auto --dist loadfile \
  tests/compiler/integration/test_build_script.py \
  tests/compiler/integration/test_cli_runtime_smoke \
  tests/compiler/integration/test_cli_semantic_codegen_runtime \
  tests/compiler/integration/test_cli_interfaces_runtime -q
./scripts/golden.sh --filter 'arithmetic/**'
make -C runtime test-all
```

### Exit Criteria

1. ARM hosts resolve `aarch64` as the native checked backend.
2. ARM-native pytest runtime suites pass instead of skipping.
3. ARM golden tests run through the normal runner path.
4. `x86_64` host behavior remains unchanged except for the new target registry and selector support.
5. Documentation reflects the new multi-target checked compiler reality.

### Checklist

- [ ] Switch the checked default target to host-native registry resolution.
- [ ] Register `aarch64` as the ARM native runtime backend.
- [ ] Remove the current ARM native-runtime skips by enabling real execution instead.
- [ ] Update build/run script tests for host-native success-path behavior.
- [ ] Run the full ARM pytest suite.
- [ ] Run the full ARM golden suite.
- [ ] Re-run runtime C harnesses on ARM.
- [ ] Re-run representative x86 runtime and golden coverage.
- [ ] Refresh README, test docs, and ABI documentation.

---

## Key Risks And Mitigations

### AArch64 Relocation And Symbol Addressing

Risk:
The current x86 backend leans on RIP-relative addressing such as `lea ... [rip + symbol]`. AArch64 will need different symbol materialization patterns, and those patterns must work with the host toolchain defaults used by [scripts/build.sh](../scripts/build.sh).

Mitigation:

- Add dedicated AArch64 tests for function symbol addresses, metadata symbol addresses, string/data literals, and runtime type descriptors.
- Validate explicit-target builds with the real `cc` linker path before enabling host-native default selection.

### Test Drift Between Compiler Registry And Test Capability Matrix

Risk:
If compiler target selection and test capability registration live in separate hard-coded tables, one of them will be forgotten when `aarch64` lands.

Mitigation:

- Make the test capability layer delegate to compiler-owned target metadata starting in slice 1.

### Over-Copying X86 Helpers Into The AArch64 Package

Risk:
The easiest short-term path is to copy `x86_64_sysv` helper modules wholesale, including runtime-layout constants that are not architecture-specific.

Mitigation:

- Slice 2 explicitly extracts shared runtime-layout and target-test scaffolding first.

### CLI Tests That Quietly Depend On X86 Defaults

Risk:
Compile-only integration tests that assert x86-specific assembly or log text will start failing on ARM once the checked default becomes host-native.

Mitigation:

- Audit those tests in slice 5 and pin the target explicitly wherever the assertion is architecture-specific.

## Final Validation Matrix

After slice 6, the repository should be validated with this matrix:

### On `aarch64` Host

- `/bin/python3 -m pytest -n auto --dist loadfile`
- `./scripts/golden.sh`
- `make -C runtime clean test-all`

### On `x86_64` Host

- `/bin/python3 -m pytest -n auto --dist loadfile`
- `./scripts/golden.sh`
- `make -C runtime clean test-all`

### Cross-Target Spot Checks

- `nifc --target x86_64_sysv ...`
- `nifc --target aarch64 ...`
- `./scripts/build.sh <program> <output> -- --target x86_64_sysv`
- `./scripts/build.sh <program> <output> -- --target aarch64`

Those spot checks matter even after the host-native default switch, because they keep the target selector itself under test instead of only the host-default path.