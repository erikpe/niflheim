# Backend IR Phase 6 Implementation Plan

Status: proposed.

This document expands phase 6 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 6 work only:

- switching the default checked backend path from the legacy codegen pipeline to backend IR plus the new `x86-64 SysV` backend
- removing or retiring the legacy tree-to-assembly backend path once parity is already proven
- cleaning up compatibility shims, obsolete legacy analyses, and no-longer-needed dual-path CLI wiring
- re-running the full repository validation gate with backend IR as the only checked backend input

It does not include post-transition optimization work, register allocation, SSA construction, or adding a second hardware backend.

## Implementation Rules

Use these rules for every phase-6 patch:

1. Do not begin cutover work until the phase-5 parity gate is actually green. Phase 6 assumes the explicit new backend selector already passes the full backend, integration, golden, and runtime gates.
2. Switch one user-visible seam at a time. Prefer a staged cutover where CLI defaults, script defaults, and test helpers are updated in small, reviewable slices rather than one large deletion patch.
3. Preserve backend IR dump and stop-after tooling as first-class checked-path seams. Cutover removes the legacy checked backend, not the backend IR debugging interfaces.
4. Remove legacy production code only after the new path owns the equivalent responsibility. If a legacy helper still contains the only implementation of a required behavior, migrate or duplicate that behavior into the new backend first.
5. Keep compatibility shims short-lived and explicit. If a temporary alias or wrapper is needed during cutover, it should exist only to ease the transition between slices and should be deleted by the end of phase 6.
6. Prefer deleting dead code over leaving dormant legacy branches. Once the new backend is the only checked path, obsolete backend toggles, dual-path helpers, and tree-walk analyses should be removed rather than silently retained.
7. Preserve deterministic observable behavior: CLI output, assembly text stability, metadata ordering, symbol naming, dump formats, and runtime behavior must remain stable across the cutover.
8. Keep docs and scripts aligned with the code at each slice. The README, transition-plan docs, helper scripts, and integration helpers should not describe stale backend-selection behavior.
9. Re-run broad validation after every slice that changes the default checked path, test helpers, or deletion of legacy runtime-root or layout logic.
10. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [ ] PR 1: Make backend IR plus `x86_64_sysv` the default checked CLI backend while preserving backend IR dump and stop-after seams.
2. [ ] PR 2: Update scripts, integration helpers, and test harness defaults to assume backend IR as the checked path.
3. [ ] PR 3: Remove legacy checked-path codegen entrypoints, dual-path CLI branches, and obsolete compatibility wrappers.
4. [ ] PR 4: Remove legacy layout, root-liveness, root-slot, and tree-walk backend analyses from production use.
5. [ ] PR 5: Remove obsolete legacy backend tests or rewrite them against the new backend surface, then run the full repository validation gate.

## PR 1: Default Checked CLI Cutover To Backend IR Plus `x86_64_sysv`

### Goal

Make backend IR plus the new `x86_64 SysV` backend the default checked compilation path while keeping backend IR dump and stop-after seams available for debugging.

### Primary Files To Change

New files:

- none expected unless a small backend-selection helper module is cleaner than expanding `compiler/cli.py`

Existing files:

- `compiler/cli.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`
- `compiler/backend/targets/api.py`
- `compiler/backend/analysis/pipeline.py` only if the default checked entrypoint needs a narrower or more explicit orchestration surface
- `tests/compiler/integration/test_cli_codegen.py`
- `tests/compiler/integration/test_cli_backend_ir_dump.py`
- `tests/compiler/integration/test_cli_backend_ir_passes.py`
- `tests/compiler/integration/test_cli_backend_ir_flags.py`
- `tests/compiler/integration/test_cli_errors.py`

### What To Change

1. Replace the legacy checked assembly path in `compiler/cli.py` with the backend IR path.
   The default selector-less checked flow should now:
   - resolve, typecheck, lower, optimize, and link
   - lower to backend IR
   - run the backend IR pass pipeline
   - emit assembly through the `x86_64_sysv` backend

2. Preserve backend IR dump and stop-after behavior.
   `--dump-backend-ir`, `--dump-backend-ir-dir`, `--stop-after backend-ir`, and `--stop-after backend-ir-passes` should continue to work on the default checked path after cutover.

3. Decide the fate of the explicit experimental selector introduced in phase 4 or 5.
   A reasonable phase-6 behavior is:
   - make it a no-op alias to the default checked path for one slice, or
   - remove it immediately with a deterministic error and updated help text
   Choose one and document it in tests.

4. Keep unsupported-flag behavior deterministic.
   Any flags that were only meaningful to the legacy checked backend should now either map cleanly to the new backend options or fail with an updated error message.

5. Ensure logging and diagnostics still describe the actual pipeline phases.
   The CLI should no longer imply that checked codegen emits directly from `LoweredLinkedSemanticProgram`.

### What To Test

1. Default checked compilation now routes through backend IR plus the `x86_64_sysv` backend.
2. Backend IR dump and stop-after flags still behave correctly after cutover.
3. Legacy-only backend selector behavior is updated deterministically.
4. CLI logging and error messages reflect the new default path.
5. Existing checked-path integration samples still compile and run correctly.

### How To Test

Focused commands:

```text
pytest tests/compiler/integration/test_cli_codegen.py -q
pytest tests/compiler/integration/test_cli_backend_ir_dump.py -q
pytest tests/compiler/integration/test_cli_backend_ir_passes.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_backend_ir_passes.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_errors.py -q
```

### Expected Outcome

- Backend IR plus `x86_64_sysv` is now the default checked backend path.
- Backend IR debugging seams remain intact and usable.
- The CLI surface reflects the actual post-transition checked pipeline.

### Checklist

- [ ] Switch the default checked CLI path to backend IR plus `x86_64_sysv`.
- [ ] Preserve backend IR dump and stop-after seams.
- [ ] Resolve the explicit experimental selector behavior.
- [ ] Update checked-path logging and diagnostics.
- [ ] Re-run focused CLI coverage for the new default path.

## PR 2: Script, Helper, And Harness Default Cutover

### Goal

Update repository scripts, test helpers, and harness defaults so they all assume backend IR as the checked backend path without requiring special flags.

### Primary Files To Change

New files:

- none expected

Existing files:

- `scripts/build.sh`
- `scripts/run.sh`
- `scripts/test.sh`
- `scripts/golden.sh`
- `tests/compiler/integration/helpers.py`
- `tests/compiler/codegen/helpers.py` if still present and still used by active tests
- `README.md`
- `docs/BACKEND_IR_TRANSITION_PLAN.md`
- `docs/BACKEND_IR_PHASE4_IMPLEMENTATION_PLAN.md` and `docs/BACKEND_IR_PHASE5_IMPLEMENTATION_PLAN.md` only if their scope notes or checklists need a post-cutover status note

### What To Change

1. Update helper scripts to rely on the new default checked backend path.
   Remove any now-unnecessary forwarding of explicit experimental backend flags from:
   - build helpers
   - run helpers
   - golden drivers
   - repository test scripts

2. Update test helpers to match the new default.
   Integration and backend helper functions should no longer need to opt into backend IR codegen explicitly for ordinary checked compilation.

3. Keep backend IR debugging workflows documented.
   README and script help text should continue to describe backend IR dump and stop-after usage where still relevant.

4. Update docs that still describe the legacy checked path as the default.
   This includes transition or status language that now becomes historical rather than planned behavior.

5. Re-run script-level smoke tests.
   The repository’s common local workflows should still function with the new checked backend path after the helper cutover.

### What To Test

1. `scripts/build.sh` and `scripts/run.sh` still work without extra backend-selection flags.
2. Golden-driver plumbing still works on the default checked path.
3. Integration helpers compile and run samples correctly without an explicit new-backend selector.
4. Updated docs and script help text match the actual default checked pipeline.
5. Repository test-driver scripts still complete successfully.

### How To Test

Focused commands:

```text
pytest tests/compiler/integration/test_cli_codegen.py -q
./scripts/golden.sh --filter 'arithmetic/**'
./scripts/test.sh
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/integration tests/compiler/backend -q
./scripts/golden.sh --filter 'arithmetic/**'
```

### Expected Outcome

- Repository scripts and test helpers all assume backend IR as the checked backend path.
- Common local workflows no longer depend on explicit backend-selection flags.
- User-facing docs describe the real default checked flow accurately.

### Checklist

- [ ] Update scripts to rely on the new default checked backend path.
- [ ] Update integration and test helpers to remove explicit new-backend opt-in.
- [ ] Refresh README and transition-plan wording for the new default.
- [ ] Re-run script and helper smoke tests.
- [ ] Keep backend IR debugging workflows documented.

## PR 3: Remove Legacy Checked-Path Entrypoints, Dual-Path Branches, And Compatibility Wrappers

### Goal

Remove the obsolete dual-path checked compilation scaffolding now that the backend IR path is the default and only checked backend.

### Primary Files To Change

New files:

- none expected

Existing files:

- `compiler/cli.py`
- `compiler/codegen/generator.py`
- `compiler/codegen/program_generator.py`
- `compiler/semantic/lowering/executable.py`
- `compiler/codegen/__init__.py`
- `tests/compiler/integration/test_cli_errors.py`
- any small compatibility shims added during phase 4 or 5 to ease selector-based bring-up

### What To Change

1. Remove legacy checked-path orchestration that is no longer used in production.
   This includes:
   - CLI branches that only existed to choose between legacy and backend IR codegen
   - transitional aliases or wrappers around experimental backend selection
   - stale helper paths that build `LoweredLinkedSemanticProgram` only for checked assembly emission

2. Retain only the pieces of legacy modules still needed for non-production or archival reasons if there is a clear justification.
   If a legacy module no longer serves tests, tools, or documentation, delete it instead of leaving it dormant.

3. Keep import graphs clean after deletion.
   Remove dead imports, stale type references, and obsolete comments that still describe the pre-cutover dual-path design.

4. Update tests that asserted dual-path behavior.
   Tests should now assert the new single checked backend path rather than the existence of a legacy fallback.

### What To Test

1. The CLI no longer contains or exposes dead dual-path checked-backend branches.
2. No active checked-path helper still depends on `LoweredLinkedSemanticProgram` assembly emission.
3. Import graphs and public module surfaces remain valid after deletion.
4. Updated tests reflect the single checked backend design.
5. Ordinary checked-path compile and run flows remain green after code removal.

### How To Test

Focused command:

```text
pytest tests/compiler/integration/test_cli_errors.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/integration tests/compiler/backend tests/compiler/semantic -q
```

### Expected Outcome

- The repository no longer carries dead checked-path dual-backend scaffolding.
- The only checked assembly path is backend IR plus `x86_64_sysv`.
- Transitional wrappers introduced during bring-up are gone.

### Checklist

- [ ] Remove dual-path checked-backend CLI branches.
- [ ] Remove obsolete checked-path compatibility wrappers.
- [ ] Clean up dead imports, comments, and stale type references.
- [ ] Update tests that asserted selector-era behavior.
- [ ] Re-run integration coverage after code removal.

## PR 4: Remove Legacy Layout, Root-Liveness, Root-Slot, And Tree-Walk Backend Analyses From Production Use

### Goal

Delete or retire the legacy correctness-critical backend analyses now that backend IR CFG analyses and target-root synchronization own the production behavior.

### Primary Files To Change

New files:

- none expected unless a short migration note or deprecation shim is justified temporarily

Existing files:

- `compiler/codegen/layout.py`
- `compiler/codegen/root_liveness.py`
- `compiler/codegen/root_slot_plan.py`
- `compiler/codegen/emitter_stmt.py`
- `compiler/codegen/emitter_expr.py`
- `compiler/codegen/emitter_fn.py`
- `compiler/codegen/walk.py`
- any backend-context modules that still snapshot or consult tree-walk liveness state in production code
- `tests/compiler/codegen/test_emit_asm_runtime_roots.py`
- `tests/compiler/codegen/test_layout.py`
- `tests/compiler/codegen/test_root_liveness.py`
- `tests/compiler/codegen/test_root_slot_plan.py`

### What To Change

1. Remove production dependence on legacy tree-walk analyses entirely.
   The checked backend path should no longer consult:
   - statement-tree root liveness
   - legacy root-slot coloring
   - legacy stack layout planning
   - per-statement dead-root clearing workarounds

2. Delete obsolete legacy modules when they no longer support active tests or documentation.
   If some are kept temporarily for historical comparison tests, move them clearly out of the production import path.

3. Rewrite any remaining root-correctness tests against backend IR or target-backend surfaces.
   Tests that still matter should assert the new analysis and emission seams rather than legacy internal helper shapes.

4. Remove comments or TODOs that describe the loop-root-clearing workaround as production behavior.
   After phase 6, that workaround should only survive as historical context in docs or commit history, not in active code.

### What To Test

1. No production checked path imports or calls legacy layout or root-liveness modules.
2. Root-correctness behavior is still covered by backend-target tests after legacy deletion.
3. Loop-carried reference behavior remains correct without tree-walk workaround code.
4. Dead legacy analysis tests are either removed or intentionally rewritten.
5. Full backend and integration coverage remain green after the deletion.

### How To Test

Focused command:

```text
pytest tests/compiler/backend tests/compiler/integration -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend tests/compiler/integration tests/compiler/runtime -q
```

### Expected Outcome

- Legacy tree-walk backend analyses are no longer part of production checked compilation.
- Root correctness is owned entirely by backend IR analyses plus target-backend emission.
- Historical loop-root workaround logic is gone from active code.

### Checklist

- [ ] Remove production use of legacy layout and root-analysis modules.
- [ ] Delete or retire obsolete legacy analysis modules.
- [ ] Rewrite any still-relevant tests against backend IR or target-backend surfaces.
- [ ] Remove stale workaround comments and TODOs.
- [ ] Re-run broad backend and integration coverage after deletion.

## PR 5: Legacy Test Cleanup And Full Repository Validation Gate

### Goal

Finish the transition by cleaning up obsolete legacy-backend tests and then passing the full repository validation gate with backend IR as the only checked backend input.

### Primary Files To Change

New files:

- none expected unless the full gate reveals a missing integration regression file worth adding explicitly

Existing files:

- `tests/compiler/codegen/` legacy-path tests that no longer apply after cutover
- `tests/compiler/backend/` target and analysis tests that need final parity assertions
- `tests/compiler/integration/` checked-path tests
- `README.md`
- `docs/BACKEND_IR_TRANSITION_PLAN.md`
- `docs/BACKEND_IR_PHASE6_IMPLEMENTATION_PLAN.md`

### What To Change

1. Remove or rewrite tests that only asserted legacy implementation details.
   Keep tests that still validate user-visible behavior, but rewrite them against:
   - backend-target assembly surfaces
   - checked CLI behavior
   - backend IR dump and stop-after seams

2. Tighten final docs around the completed transition.
   Once the full gate is green, docs should describe backend IR as the checked backend seam rather than a migration in progress.

3. Run the full repository validation gate.
   This slice is not complete until the following all pass on the cutover codebase:
   - full compiler pytest suite
   - full golden suite
   - full runtime harness suite
   - repository umbrella test script

4. Record any residual risks as explicit follow-on work outside this transition plan.
   Performance, register allocation, SSA, and additional backend targets should remain clearly deferred rather than smuggled into phase 6.

### What To Test

1. Obsolete legacy-backend tests are removed or rewritten appropriately.
2. Full pytest coverage passes with backend IR as the only checked backend input.
3. Full golden coverage passes on the cutover codebase.
4. Full runtime harness coverage passes on the cutover codebase.
5. The repository umbrella test driver passes end to end.

### How To Test

Focused commands:

```text
pytest -q
./scripts/golden.sh
make -C runtime test-all
./scripts/test.sh
```

Recommended final phase gate command sequence:

```text
pytest -q
./scripts/golden.sh
make -C runtime test-all
./scripts/test.sh
```

### Expected Outcome

- Backend IR is the only checked backend input across the repository.
- The full test, golden, and runtime gates pass on the cutover codebase.
- Legacy backend implementation details are no longer represented as active checked-path tests.

### Checklist

- [ ] Remove or rewrite obsolete legacy-backend tests.
- [ ] Update docs to describe backend IR as the canonical checked backend seam.
- [ ] Pass the full compiler pytest suite.
- [ ] Pass the full golden suite and runtime harness suite.
- [ ] Pass the repository umbrella test driver.

## Phase 6 Gate Checklist

Use this checklist when phase 6 is believed to be complete.

- [ ] Backend IR plus `x86_64_sysv` is the default checked CLI backend path.
- [ ] Backend IR dump and stop-after seams remain supported after cutover.
- [ ] Repository scripts and test helpers assume backend IR as the checked backend path.
- [ ] Legacy checked-path selection scaffolding is removed.
- [ ] Legacy layout, root-liveness, and root-slot planning are removed from production use.
- [ ] Obsolete legacy backend tests are removed or rewritten against the new surfaces.
- [ ] The full pytest suite passes with backend IR as the only checked backend input.
- [ ] The full golden suite passes on the cutover codebase.
- [ ] Runtime harnesses pass on the cutover codebase.
- [ ] Repository docs describe backend IR as the canonical checked backend seam.

Recommended phase gate commands:

```text
pytest -q
./scripts/golden.sh
make -C runtime test-all
./scripts/test.sh
```

Expected phase gate outcome:

- the default checked compiler path lowers through backend IR and emits through `x86_64_sysv`
- backend IR dump and stop-after debugging seams still work
- legacy checked-backend implementation code is removed from production use
- the full repository validation gate passes on the cutover codebase