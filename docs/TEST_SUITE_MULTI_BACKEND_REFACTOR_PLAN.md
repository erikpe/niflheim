# Test Suite Multi-Backend Refactor Plan

Status: planned.

This document expands the test-suite refactor for multiple hardware backends into a concrete migration plan with ordered implementation slices.

It is intentionally limited to pytest and test-harness refactor work only:

- separating target-specific assembly-emission tests from host-native runtime contract tests
- making target-emission tests run on all hosts, even when the emitted target differs from the host architecture
- temporarily disabling host-native runtime contract tests on ARM hosts until an `aarch64` backend exists
- preparing the suite so those runtime tests re-enable through one central capability change when `aarch64` lands

It does not include:

- implementing the `aarch64` backend itself
- adding cross-toolchain assembly, cross-linking, or qemu-based execution
- changing golden-test semantics
- changing the C runtime harnesses under [tests/runtime](../tests/runtime) beyond documentation updates

It maps directly to:

- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md)
- [tests/README.md](../tests/README.md)
- [compiler/backend/targets/api.py](../compiler/backend/targets/api.py)
- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py)

## Implementation Rules

Use these rules for every slice:

1. One test must not assert both target-specific assembly shape and runtime behavior.
2. Tests under [tests/compiler/backend/targets/x86_64_sysv](../tests/compiler/backend/targets/x86_64_sysv) must assert `x86_64_sysv` surface only. They should run on both x86_64 and ARM hosts.
3. Runtime contract tests must compile for a host-native runnable backend only.
4. Temporary ARM skips must live in one shared runtime capability layer, not in leaf tests.
5. Helper APIs must make the separation explicit: emit target assembly, assemble host executable, run executable, compile native and run.
6. Prefer moving or deleting duplicated runtime scenarios rather than keeping the same behavior test in both a direct-backend suite and a CLI runtime suite.
7. Existing runtime integration directories should remain the canonical home for runtime contracts unless a new directory clearly reduces churn.
8. When `aarch64` lands, enabling ARM runtime tests should require only target-registry or fixture changes plus new `aarch64` emission tests, not edits across leaf runtime tests.
9. Keep documentation aligned as slices land. The current x86-only execution wording in [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md) and [tests/README.md](../tests/README.md) should be updated during the cleanup slices.
10. Update the checkboxes in this document as implementation progresses.

## Temporary Host Policy

This policy should be encoded in one shared test-support layer as soon as the refactor starts:

- On `x86_64` hosts, the native runtime backend is `x86_64_sysv`.
- On `aarch64` or `arm64` hosts, there is temporarily no native runtime backend. Runtime contract tests should skip with one deterministic reason emitted by shared fixtures or helpers.
- On all hosts, `x86_64_sysv` emission tests still run.
- No leaf test should call `platform.machine()` or add host-architecture `skipif` conditions directly.

## Ordered Slice Checklist

1. [x] Slice 1: Add shared host and target capability plumbing plus the temporary ARM runtime skip policy.
2. [x] Slice 2: Split helper APIs into explicit emit-only and native-runtime paths.
3. [x] Slice 3: Convert the `x86_64_sysv` target suite to emit-only coverage.
4. [x] Slice 4: Consolidate runtime contract coverage under native CLI integration suites.
5. [ ] Slice 5: Convert build and run script tests to the same native-runtime harness model.
6. [ ] Slice 6: Remove compatibility wrappers and refresh test documentation.
7. [ ] Slice 7: Enable ARM runtime contracts when `aarch64` lands.

## Slice 1: Shared Host And Target Capability Layer

### Goal

Introduce one central place that knows:

- which backend targets exist for test purposes
- which targets are emit-only versus host-runnable
- whether this host currently has a native runtime backend
- why runtime contract tests should skip when no native backend exists

### Primary Files To Change

New files:

- [tests/compiler/conftest.py](../tests/compiler/conftest.py)
- [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py)
- [tests/compiler/support/runtime_harness.py](../tests/compiler/support/runtime_harness.py)

Existing files:

- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py)

### What To Change

1. Add a shared backend-matrix model in `tests/compiler/support/backend_matrix.py`.
   It should describe:
   - target name
   - whether the target can emit on any host
   - whether the target is native-runnable on this host
   - a deterministic skip reason when no native runtime backend exists

2. Add shared fixtures in `tests/compiler/conftest.py`.
   The minimal useful fixture surface is:
   - `native_runtime_backend_name`
   - `require_native_runtime_backend`
   - `host_architecture`

3. Encode the temporary ARM behavior centrally.
   On `aarch64` or `arm64`, `require_native_runtime_backend` should skip with a message such as:
   `runtime contract tests require a native backend; only x86_64_sysv is registered today`

4. Keep target-emission suites host-agnostic.
   The shared capability layer should not prevent direct emission tests for `x86_64_sysv` from running on ARM.

### What To Test

1. `x86_64` hosts resolve `x86_64_sysv` as the native runtime backend.
2. ARM hosts receive one deterministic skip reason.
3. Emission-only test helpers remain usable on all hosts.

### Expected Outcome

- Host-architecture policy is centralized.
- There are no per-test architecture guards.
- Runtime contract test directories can be gated by one shared fixture in later slices.

### Checklist

- [x] Add `tests/compiler/support/backend_matrix.py`.
- [x] Add shared host and runtime fixtures in `tests/compiler/conftest.py`.
- [x] Encode the temporary ARM runtime skip policy in one place.
- [x] Add focused fixture coverage for x86 host and no-native-backend cases.

## Slice 2: Helper Split And Naming Cleanup

### Goal

Split the current helper API so emit-only paths and native-runtime paths are explicit instead of bundled together.

### Primary Files To Change

New files:

- [tests/compiler/support/runtime_execution.py](../tests/compiler/support/runtime_execution.py)
- [tests/compiler/integration/test_helpers.py](../tests/compiler/integration/test_helpers.py)
- [tests/compiler/support/test_runtime_execution.py](../tests/compiler/support/test_runtime_execution.py)

Existing files:

- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py)
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)

### What To Change

1. In [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py), split the current flow into explicit operations:
   - `compile_to_asm(...)`
   - `assemble_host_executable(...)`
   - `run_executable(...)`
   - `compile_native_and_run(...)`

2. Keep `compile_to_asm(...)` architecture-neutral.
   It should remain valid on all hosts because assembly emission itself is not the host-specific step.

3. Rename or replace `build_executable(...)`.
   The current name is too generic for a host-specific step. Rename it to `assemble_host_executable(...)` or keep a short-lived compatibility wrapper with a clear deprecation comment.

4. Remove native-execution behavior from [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py).
   Keep:
   - `emit_program(...)`
   - `emit_source_asm(...)`

   Remove or deprecate:
   - `compile_and_run_source(...)`

5. Make the new native-runtime helper depend on the shared capability layer.
   On ARM today, it should skip through the shared fixture path rather than failing deep inside `cc`.

### What To Test

1. Emit-only helpers still work on all hosts.
2. Native-runtime helpers compile and run on `x86_64` hosts.
3. Native-runtime helpers skip cleanly on ARM hosts.

### Expected Outcome

- Helper intent is explicit from the call site.
- Test reviews can distinguish “emit target asm” from “run host-native contract”.
- No target-specific helper retains hidden host-execution behavior.

### Checklist

- [x] Split `tests/compiler/integration/helpers.py` into explicit emit and runtime steps.
- [x] Rename or wrap `build_executable(...)` as a host-specific assembly step.
- [x] Remove `compile_and_run_source(...)` from the `x86_64_sysv` target helper surface.
- [x] Add focused helper coverage for emit-only and native-runtime paths.

## Slice 3: Convert The `x86_64_sysv` Target Suite To Emit-Only Coverage

### Goal

Make every test that remains under [tests/compiler/backend/targets/x86_64_sysv](../tests/compiler/backend/targets/x86_64_sysv) safe to run on any host by removing return-code and stderr assertions from that tree.

### Primary Files To Change

Existing files:

- [tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_strings.py](../tests/compiler/backend/targets/x86_64_sysv/test_strings.py)
- [tests/compiler/backend/targets/x86_64_sysv/test_suite_boundaries.py](../tests/compiler/backend/targets/x86_64_sysv/test_suite_boundaries.py)

### What To Change

1. Remove `compile_and_run_source(...)` usage from the `x86_64_sysv` target tree.

2. Keep emission-shape tests in place.
   Examples:
   - instruction-family checks
   - frame layout checks
   - ABI call-shape checks
   - label or symbol checks
   - fast-path lowering checks
   - debug metadata checks

3. Move runtime-behavior cases out of the `x86_64_sysv` tree.
   Runtime cases include tests that assert:
   - process return code
   - panic text in stderr
   - user-visible runtime behavior

4. If a runtime case also carried a useful assembly assertion, split it into two tests:
   - one emit-only target test kept in place
   - one native runtime contract test moved in Slice 4

5. Do not add target or host guards to these files.
   After this slice, every test remaining in the `x86_64_sysv` tree should run unchanged on ARM and x86_64 hosts.

### What To Test

1. The full `x86_64_sysv` target suite passes on both x86_64 and ARM hosts without any runtime skips.
2. No file under the `x86_64_sysv` tree imports the host-native runtime helper.

### Expected Outcome

- The `x86_64_sysv` suite becomes a pure target-emission suite.
- `x86_64_sysv` tests become valid all-host coverage.

### Checklist

- [x] Remove `compile_and_run_source(...)` imports and usages from the `x86_64_sysv` target tree.
- [x] Keep or add emit-only assertions where useful.
- [x] Move or split every runtime-returncode or runtime-stderr test.
- [x] Re-run the full `x86_64_sysv` target suite on ARM and x86_64 hosts.

Current validation state:

- [x] Re-ran the full `x86_64_sysv` target suite on ARM hosts.
- [x] Re-ran the full `x86_64_sysv` target suite on an `x86_64` host.

## Slice 4: Consolidate Runtime Contract Coverage Under Native CLI Integration Suites

### Goal

Make the existing CLI runtime integration directories the canonical home for runtime contracts, and migrate runtime cases out of the direct `x86_64_sysv` target tree.

### Primary Files To Change

Existing files and directories:

- [tests/compiler/integration/test_cli_runtime_smoke](../tests/compiler/integration/test_cli_runtime_smoke)
- [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime)
- [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime)
- [tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py](../tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py)

New files likely needed:

- [tests/compiler/integration/test_cli_runtime_smoke/conftest.py](../tests/compiler/integration/test_cli_runtime_smoke/conftest.py)
- [tests/compiler/integration/test_cli_semantic_codegen_runtime/conftest.py](../tests/compiler/integration/test_cli_semantic_codegen_runtime/conftest.py)
- [tests/compiler/integration/test_cli_interfaces_runtime/conftest.py](../tests/compiler/integration/test_cli_interfaces_runtime/conftest.py)
- [tests/compiler/integration/test_cli_runtime_smoke/test_basic_control_flow_runtime.py](../tests/compiler/integration/test_cli_runtime_smoke/test_basic_control_flow_runtime.py)
- [tests/compiler/integration/test_cli_runtime_smoke/test_callable_values_runtime.py](../tests/compiler/integration/test_cli_runtime_smoke/test_callable_values_runtime.py)
- [tests/compiler/integration/test_cli_runtime_smoke/test_double_and_object_runtime.py](../tests/compiler/integration/test_cli_runtime_smoke/test_double_and_object_runtime.py)
- [tests/compiler/integration/test_cli_runtime_smoke/test_program_args_runtime.py](../tests/compiler/integration/test_cli_runtime_smoke/test_program_args_runtime.py)
- [tests/compiler/integration/test_cli_runtime_smoke/test_string_and_resolution_runtime.py](../tests/compiler/integration/test_cli_runtime_smoke/test_string_and_resolution_runtime.py)
- [tests/compiler/integration/test_cli_interfaces_runtime/test_interface_typed_locals.py](../tests/compiler/integration/test_cli_interfaces_runtime/test_interface_typed_locals.py)

### What To Change

1. Gate the runtime contract directories through one directory-level fixture.
   Use package-level `conftest.py` files or one higher-level integration `conftest.py` to require `require_native_runtime_backend`.

2. Keep compile-only and policy tests where they are.
   Files such as [tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py](../tests/compiler/integration/test_cli_backend_ir_codegen_reduced.py) and [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py) should retain:
   - default-target wiring checks
   - emit-to-asm checks
   - CLI flag behavior checks

3. Move runtime cases into the native CLI runtime suites.
   Use this migration map:

   - runtime cases from [tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py)
     -> new or existing files under [tests/compiler/integration/test_cli_runtime_smoke](../tests/compiler/integration/test_cli_runtime_smoke)

   - runtime cases from [tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py), [tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py), [tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py), [tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py), [tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py), and [tests/compiler/backend/targets/x86_64_sysv/test_strings.py](../tests/compiler/backend/targets/x86_64_sysv/test_strings.py)
     -> behavior-grouped files under [tests/compiler/integration/test_cli_runtime_smoke](../tests/compiler/integration/test_cli_runtime_smoke)

   - runtime cases from [tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py)
     -> existing GC and root-sensitive files under [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime)

   - runtime cases from [tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_dispatch.py)
     -> [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime) and the existing virtual-dispatch files under [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime)

   - runtime cases from [tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py](../tests/compiler/backend/targets/x86_64_sysv/test_emit_casts.py)
     -> panic and cast behavior files under [tests/compiler/integration/test_cli_runtime_smoke](../tests/compiler/integration/test_cli_runtime_smoke)

4. Prefer CLI runtime coverage as the canonical runtime surface.
   Do not keep the same return-code or panic scenario in both the direct target suite and CLI integration unless there is a clear extra contract only one surface can assert.

5. Translate direct-backend `skip_optimize=True` cases carefully.
   If the runtime scenario only needs semantic correctness, migrate it to the default checked CLI path.
   If the scenario intentionally validates unoptimized or optimization-sensitive behavior, move it into [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime) and express the configuration with CLI flags such as `--disable-all-optimization` rather than direct backend helpers.

### What To Test

1. Runtime integration suites pass on x86_64 hosts.
2. The same directories skip cleanly on ARM hosts through the shared fixture.
3. No x86-specific direct-backend runtime tests remain.

### Expected Outcome

- Runtime behavior is tested through one native CLI integration surface.
- ARM hosts skip those suites cleanly for now.
- The same runtime tests will become runnable on ARM once `aarch64` is registered.

### Checklist

- [x] Add directory-level runtime gating for the CLI runtime suites.
- [x] Move general runtime behavior cases into `test_cli_runtime_smoke`.
- [x] Move GC and root-sensitive cases into `test_cli_semantic_codegen_runtime`.
- [x] Move interface and dispatch cases into `test_cli_interfaces_runtime` or existing virtual-dispatch runtime files.
- [x] Remove duplicated direct-backend runtime scenarios once equivalent CLI coverage exists.

Current validation state:

- [x] Runtime integration suites skip cleanly on ARM hosts through the shared runtime fixture.
- [x] Runtime integration suites pass on `x86_64` hosts.

## Slice 5: Convert Build And Run Script Tests To The Native-Runtime Harness Model

### Goal

Bring the script integration tests into the same emit-only versus native-runtime split, so script tests do not become a second place where host-architecture assumptions leak.

### Primary Files To Change

Existing files:

- [tests/compiler/integration/test_build_script.py](../tests/compiler/integration/test_build_script.py)
- [scripts/build.sh](../scripts/build.sh)
- [scripts/run.sh](../scripts/run.sh)

### What To Change

1. Split script tests by responsibility.
   Keep architecture-agnostic tests for:
   - missing-archive handling
   - argument validation
   - deterministic output-path behavior that does not require successful native execution

2. Gate native script success-path tests behind the shared runtime capability layer.
   Examples:
   - successful `build.sh` compilation to a runnable executable
   - successful `run.sh` execution with asserted exit code

3. Keep skip reasons centralized.
   Script tests should rely on the same `require_native_runtime_backend` path used by the runtime CLI suites rather than adding new host checks.

### What To Test

1. Script argument and validation tests still run everywhere.
2. Script success-path native execution tests pass on x86_64 hosts and skip cleanly on ARM hosts.

### Expected Outcome

- Script tests follow the same architecture policy as the runtime integration suites.
- Native execution assumptions remain centralized.

### Checklist

- [x] Split script tests into architecture-agnostic checks and native-runtime checks.
- [x] Gate script success-path execution tests through the shared runtime fixture.
- [ ] Re-run the script test file on x86_64 and confirm deterministic skip behavior on ARM.

Current validation state:

- [x] The script test file skips native-runtime cases cleanly on ARM hosts through the shared runtime fixture.
- [ ] The script test file passes on an `x86_64` host.

## Slice 6: Remove Compatibility Wrappers And Refresh Test Documentation

### Goal

Delete temporary helper shims and update docs so the suite structure and host policy are described accurately.

### Primary Files To Change

Existing files:

- [tests/compiler/integration/helpers.py](../tests/compiler/integration/helpers.py)
- [tests/compiler/backend/targets/x86_64_sysv/helpers.py](../tests/compiler/backend/targets/x86_64_sysv/helpers.py)
- [tests/README.md](../tests/README.md)
- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md)
- this document

### What To Change

1. Remove short-lived compatibility wrappers.
   Candidates include any temporary aliases retained during Slice 2, especially wrappers that obscure whether a helper is emit-only or native-runtime.

2. Update [tests/README.md](../tests/README.md).
   Document the new split between:
   - target-emission suites
   - native CLI runtime contract suites
   - C runtime harnesses under `tests/runtime`

3. Update [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md).
   Replace the current x86-only runtime wording with the refactored policy:
   - target-specific emission tests are all-host
   - runtime contract tests run on hosts that have a native backend
   - ARM is temporarily skipped until `aarch64` exists

### What To Test

1. No test uses deprecated helper names.
2. Test docs describe the current architecture policy accurately.

### Expected Outcome

- The helper surface is clean and explicit.
- Documentation matches the real suite structure.

### Checklist

- [ ] Remove compatibility wrappers introduced during migration.
- [ ] Update `tests/README.md` for the new suite split.
- [ ] Update `docs/TEST_PLAN_v0.1.md` for the new host policy.
- [ ] Re-run a representative cross-section of target-emission and runtime suites.

## Slice 7: Enable ARM Runtime Contracts When `aarch64` Lands

### Goal

Turn the temporary ARM runtime skip into runnable native coverage with minimal test-suite churn.

### Primary Files To Change

New files:

- [compiler/backend/targets/aarch64](../compiler/backend/targets/aarch64)
- [tests/compiler/backend/targets/aarch64](../tests/compiler/backend/targets/aarch64)

Existing files:

- [tests/compiler/support/backend_matrix.py](../tests/compiler/support/backend_matrix.py)
- [tests/compiler/conftest.py](../tests/compiler/conftest.py)
- any CLI target-selection surface that needs explicit `aarch64` support

### What To Change

1. Register `aarch64` as the native runtime backend on ARM hosts in the shared backend matrix.

2. Keep the runtime contract suites unchanged.
   The objective is that [tests/compiler/integration/test_cli_runtime_smoke](../tests/compiler/integration/test_cli_runtime_smoke), [tests/compiler/integration/test_cli_semantic_codegen_runtime](../tests/compiler/integration/test_cli_semantic_codegen_runtime), and [tests/compiler/integration/test_cli_interfaces_runtime](../tests/compiler/integration/test_cli_interfaces_runtime) start running on ARM through the fixture change alone.

3. Add an `aarch64` target-emission suite parallel to the existing `x86_64_sysv` tree.
   That suite should follow the same emit-only rule established in Slice 3.

4. Remove or update focused tests that asserted the temporary ARM skip reason.

### What To Test

1. ARM hosts now run the native runtime contract suites.
2. `aarch64` target-emission tests run on all hosts.
3. Existing runtime contract tests need no leaf edits to become active on ARM.

### Expected Outcome

- ARM runtime contracts are enabled through shared capability changes, not broad test edits.
- The suite now supports multiple hardware backends with a stable structure.

### Checklist

- [ ] Register `aarch64` as a native runtime backend on ARM hosts.
- [ ] Add the `aarch64` emit-only target suite.
- [ ] Confirm existing runtime contract suites run unchanged on ARM.
- [ ] Remove temporary ARM skip expectation tests.

## Enablement Checklist For `aarch64`

When the `aarch64` backend lands later, enabling the temporarily skipped ARM runtime tests should require only the following changes:

1. [ ] Add `compiler/backend/targets/aarch64/` and register it in the backend target registry.
2. [ ] Add `--target aarch64` CLI coverage.
3. [ ] Update `tests/compiler/support/backend_matrix.py` so `native_runtime_backend_name` resolves to `aarch64` on ARM hosts.
4. [ ] Add an `aarch64` target-emission suite parallel to `tests/compiler/backend/targets/x86_64_sysv/`.
5. [ ] Run `tests/compiler/integration/test_cli_runtime_smoke/`, `tests/compiler/integration/test_cli_semantic_codegen_runtime/`, and `tests/compiler/integration/test_cli_interfaces_runtime/` on ARM hosts without changing individual test bodies.

If additional work is required beyond those steps, that is a sign the refactor did not centralize the native-runtime decision deeply enough.