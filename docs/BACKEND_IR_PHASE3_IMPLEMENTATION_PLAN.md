# Backend IR Phase 3 Implementation Plan

Status: proposed.

This document expands phase 3 from [docs/BACKEND_IR_TRANSITION_PLAN.md](BACKEND_IR_TRANSITION_PLAN.md) into a concrete implementation checklist with PR-sized slices.

It is intentionally limited to phase 3 work only:

- CFG indexing over backend IR callables
- unreachable-block elimination and basic CFG simplification
- virtual-register liveness on backend IR
- safepoint and reference liveness on backend IR
- named root-slot planning from backend IR liveness
- stack-home planning and deterministic block ordering for later target emission
- checked-path wiring for a real `backend-ir-passes` phase boundary

It does not include target instruction selection, physical frame offsets, register allocation, or end-to-end assembly emission from backend IR.

## Implementation Rules

Use these rules for every phase-3 patch:

1. Consume verified backend IR from phase 2. Do not reintroduce any dependence on `LoweredLinkedSemanticProgram` tree walks for correctness decisions.
2. Keep backend analyses target-neutral. Phase 3 may assign symbolic stack homes and root-slot indices, but it must not assign physical registers or concrete stack offsets.
3. Keep cleanup passes and dataflow analyses separate. Mutating CFG cleanup should live in its own modules; liveness and planning should read a stable CFG view.
4. Preserve surviving callable, register, block, and instruction IDs. Cleanup passes may remove unreachable blocks or forward jumps, but they must not renumber the remaining IR.
5. Use deterministic traversal orders everywhere: callable order, block order, predecessor order, instruction order, and worklist requeue order must be stable across runs.
6. Reuse backend IR metadata already copied into the IR in phase 2. In particular, safepoint and GC decisions should come from `BackendEffects` and call-target metadata, not from semantic-expression reinspection.
7. Port or mirror existing correctness coverage from the legacy backend analysis tests before deleting or bypassing the old logic.
8. Keep optional analysis-dump serialization out of scope unless it becomes necessary for review or debugging. Direct Python-level assertions are sufficient for phase 3.
9. Keep the default checked assembly path unchanged. Phase 3 may wire `--stop-after backend-ir-passes`, but normal `codegen` must still use the legacy backend until phase 4 and phase 5 are complete.
10. Update the checkboxes in this document as work lands so the doc stays live.

## Ordered PR Checklist

1. [x] PR 1: Add CFG indexing utilities, analysis fixtures, and shared pass entrypoints.
2. [ ] PR 2: Implement unreachable-block elimination and basic CFG simplification.
3. [ ] PR 3: Implement virtual-register liveness analysis.
4. [ ] PR 4: Implement safepoint and reference liveness analysis.
5. [ ] PR 5: Implement named root-slot planning from backend safepoint liveness.
6. [ ] PR 6: Implement stack-home planning for backend registers and temporaries.
7. [ ] PR 7: Implement deterministic block ordering, the backend pass pipeline, and checked-path `backend-ir-passes` CLI wiring.

## PR 1: CFG Indexing Utilities, Analysis Fixtures, And Shared Pass Entrypoints

### Goal

Create the shared analysis foundation so later phase-3 slices operate on one explicit CFG index and one consistent testing harness instead of rebuilding ad hoc predecessor and traversal logic in each pass.

### Primary Files To Change

New files:

- `compiler/backend/analysis/cfg.py`
- `tests/compiler/backend/analysis/helpers.py`
- `tests/compiler/backend/analysis/test_cfg.py`

Existing files:

- `compiler/backend/analysis/__init__.py`
- [compiler/backend/ir/model.py](../compiler/backend/ir/model.py) only if a small shared analysis result type or helper belongs there
- [compiler/backend/ir/verify.py](../compiler/backend/ir/verify.py) only if a small shared CFG helper can be extracted cleanly without weakening verifier clarity
- [tests/compiler/backend/lowering/helpers.py](../tests/compiler/backend/lowering/helpers.py) only if a generic source-to-backend-IR helper is worth sharing directly

### What To Change

1. Add `compiler/backend/analysis/cfg.py` as the shared CFG utility module for backend IR callables.
   It should expose deterministic helpers for:
   - predecessor maps
   - successor maps
   - reachable-block discovery
   - reverse-postorder or other stable traversal order used by later passes
   - per-block instruction iteration helpers when tests need stable snapshots

2. Keep CFG derivation aligned with the verifier.
   The analysis package should not invent a second notion of successors. Either share small helpers with the verifier or mirror the same terminator rules exactly:
   - jump has one successor
   - branch has two distinct successors
   - return and trap have none

3. Add shared analysis test helpers under `tests/compiler/backend/analysis/helpers.py`.
   These helpers should compile representative source programs through the phase-2 lowering entrypoint and return:
   - the verified `BackendProgram`
   - convenient callable lookup helpers
   - optional direct IR fixture builders for malformed or hand-shaped CFG tests

4. Freeze the pass entrypoint shape now.
   A reasonable phase-3 convention is:
   - per-pass functions that accept one `BackendCallableDecl` plus shared CFG indexes when appropriate
   - one program-level pipeline entrypoint added later in phase 3
   Keep the signatures explicit so tests can run each pass independently.

5. Do not mutate IR in this slice.
   PR 1 should establish indexing and fixtures only.

### What To Test

1. Branch and loop callables produce correct predecessor and successor maps.
2. Reachability from `entry_block_id` is deterministic and matches verifier expectations.
3. Traversal order is stable across repeated runs.
4. Extern callables and minimal concrete callables are handled cleanly.
5. Shared lowering helpers are reusable by later analysis tests without duplicating setup.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_cfg.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_cfg.py tests/compiler/backend/ir/test_verify.py tests/compiler/backend/lowering/test_control_flow.py -q
```

### Expected Outcome

- Backend analysis code has one canonical CFG view.
- Later dataflow passes can share deterministic block traversal and predecessor indexing.
- Analysis tests can build lowered backend fixtures without repeating the full compiler setup.

### Checklist

- [x] Add `compiler/backend/analysis/cfg.py`.
- [x] Add reusable backend-analysis test helpers.
- [x] Add deterministic predecessor, successor, reachability, and traversal coverage.
- [x] Keep IR mutation deferred to the next slice.

## PR 2: Unreachable-Block Elimination And Basic CFG Simplification

### Goal

Implement the minimal CFG cleanup passes needed so later liveness and planning operate on a clean, explicit backend CFG instead of carrying obviously dead or redundant blocks forward.

### Primary Files To Change

New files:

- `compiler/backend/analysis/simplify_cfg.py`
- `tests/compiler/backend/analysis/test_simplify_cfg.py`

Existing files:

- `compiler/backend/analysis/cfg.py`
- `compiler/backend/analysis/__init__.py`
- [compiler/backend/ir/verify.py](../compiler/backend/ir/verify.py)
- [tests/compiler/backend/analysis/helpers.py](../tests/compiler/backend/analysis/helpers.py)

### What To Change

1. Add an unreachable-block elimination pass.
   For non-extern callables, remove any block that is not reachable from `entry_block_id`.
   Preserve the original block IDs of the surviving blocks; do not renumber to close ordinal gaps.

2. Add a minimal, correctness-first CFG simplifier.
   Start with only the transformations that are easy to reason about and easy to verify:
   - forward jump-only or empty intermediary blocks when the rewrite is semantics-preserving
   - collapse branches whose true and false edges target the same block into a jump if such shape can appear after cleanup
   - remove now-unreferenced blocks after forwarding

3. Keep merge-copy and edge-split structure valid.
   Do not simplify away blocks that still carry required ordinary copy instructions inserted for non-SSA joins.
   If a block contains any real instructions, leave it alone unless the rewrite is trivially correct and covered by tests.

4. Re-verify after every mutating pass.
   The simplifier should either return already-verified IR or run `verify_backend_program()` at the program level in its tests and later pipeline integration.

5. Keep copy elimination, branch inversion, and broader canonicalization out of scope.
   Phase 3 only needs the cleanup required to support correct analyses and readable dumps.

### What To Test

1. Unreachable blocks are removed from branch-heavy fixtures.
2. Forwarding through empty or jump-only blocks preserves terminator targets correctly.
3. Blocks with required merge copies are not incorrectly deleted.
4. Loops remain structurally valid after simplification.
5. Surviving block IDs and instruction IDs remain unchanged.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_simplify_cfg.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_cfg.py tests/compiler/backend/analysis/test_simplify_cfg.py tests/compiler/backend/ir/test_verify.py tests/compiler/backend/lowering/test_control_flow.py -q
```

### Expected Outcome

- Backend IR passes can rely on a reachability-pruned CFG.
- Obvious empty indirection blocks are removed before liveness and planning.
- Cleanup remains conservative enough that CFG rewrites are easy to review and debug.

### Checklist

- [ ] Add unreachable-block elimination.
- [ ] Add basic CFG forwarding or jump-threading for trivial blocks.
- [ ] Preserve merge-copy and edge-split correctness.
- [ ] Add coverage for branches, loops, and non-simplifiable join blocks.

## PR 3: Virtual-Register Liveness Analysis

### Goal

Move value liveness onto backend IR so later safepoint, root-slot, and stack-home planning reason about virtual registers directly instead of semantic locals and statement trees.

### Primary Files To Change

New files:

- `compiler/backend/analysis/liveness.py`
- `tests/compiler/backend/analysis/test_liveness.py`

Existing files:

- `compiler/backend/analysis/cfg.py`
- `compiler/backend/analysis/simplify_cfg.py`
- [compiler/backend/ir/model.py](../compiler/backend/ir/model.py) only if a shared analysis snapshot helper is needed
- [tests/compiler/backend/analysis/helpers.py](../tests/compiler/backend/analysis/helpers.py)

### What To Change

1. Implement backward virtual-register liveness over backend basic blocks.
   Compute at least:
   - per-block `live_in`
   - per-block `live_out`
   - stable instruction-level transfer helpers needed by the safepoint pass

2. Define def-use handling for every backend instruction and terminator.
   The liveness pass should treat only `BackendRegOperand` uses as live uses.
   Data blobs and constants are not live values.

3. Make the fixed-point iteration deterministic.
   Use the same stable block ordering every run, especially for loops and multi-block joins.

4. Treat mutable backend registers as ordinary non-SSA virtual registers.
   A later definition should kill an earlier one in the same dataflow position; no SSA assumptions should leak into this pass.

5. Keep the results easy for later passes to consume.
   If `BackendFunctionAnalysisDump` is sufficient, populate its `live_in` and `live_out` shape in tests or helper adapters.
   If it is awkward, use a narrower analysis result object in `compiler/backend/analysis/` and leave serialization concerns for later.

### What To Test

1. Straight-line callables compute expected `live_in` and `live_out` sets.
2. Branch merges union successor liveness correctly.
3. Loop-carried registers converge to stable fixed points.
4. Join-copy blocks are handled correctly.
5. Dead temporaries do not remain live past their last use.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_liveness.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_liveness.py tests/compiler/backend/analysis/test_simplify_cfg.py tests/compiler/backend/lowering/test_control_flow.py tests/compiler/backend/lowering/test_backend_calls.py -q
```

### Expected Outcome

- Backend IR has a real CFG-based liveness analysis over virtual registers.
- Loop and branch liveness no longer depend on semantic statement order.
- Later safepoint and slot-planning work can consume virtual-register live sets directly.

### Checklist

- [ ] Add `compiler/backend/analysis/liveness.py`.
- [ ] Define deterministic def-use handling for all instruction and terminator kinds.
- [ ] Add branch, loop, merge, and dead-temp liveness coverage.
- [ ] Keep results target-neutral and non-SSA.

## PR 4: Safepoint And Reference Liveness Analysis

### Goal

Replace legacy named-root liveness with backend-IR safepoint analysis that computes which reference-typed virtual registers must be considered live at each GC-capable backend operation.

### Primary Files To Change

New files:

- `compiler/backend/analysis/safepoints.py`
- `tests/compiler/backend/analysis/test_safepoints.py`

Existing files:

- `compiler/backend/analysis/liveness.py`
- `compiler/backend/analysis/cfg.py`
- [compiler/backend/ir/model.py](../compiler/backend/ir/model.py)
- [compiler/codegen/root_liveness.py](../compiler/codegen/root_liveness.py) only as a migration reference until phase 6 removes legacy use
- [tests/compiler/codegen/test_root_liveness.py](../tests/compiler/codegen/test_root_liveness.py) as the coverage set to port or mirror

### What To Change

1. Define which backend operations are safepoints.
   Use backend IR information already present after phase 2:
   - `BackendCallInst.effects.may_gc`
   - `BackendCallInst.effects.needs_safepoint_hooks`
   - any other backend instruction kinds that explicitly model GC-capable runtime interaction, if added later
   Do not ask semantic lowering whether an expression may GC.

2. Derive live reference registers at each safepoint from virtual-register liveness plus register type information.
   Only registers whose `type_ref` is a reference or interface-like GC-managed type should participate in root planning.

3. Record results per safepoint instruction ID in deterministic order.
   This should line up naturally with the optional `BackendFunctionAnalysisDump.safepoint_live_regs` shape.

4. Port the legacy root-liveness regression surface onto backend IR fixtures.
   At minimum, mirror the current cases for:
   - straight-line call live roots
   - nested call continuations
   - branch merges
   - loop convergence
   - collection or l-value-like GC-capable operations
   - lowered `for in` iteration safepoints
   - nested-block live-after behavior that previously caused premature root clearing

5. Add an explicit loop-carried reference regression.
   This slice must cover the known failure mode that forced the legacy loop-clearing workaround: a reference kept live across loop back-edges must stay live at every relevant safepoint inside the loop body.

### What To Test

1. Safepoint live-register sets are correct for straight-line and nested-call cases.
2. Branch successors merge live references correctly.
3. Loop-carried references stay live across back-edges.
4. `for in` iteration safepoints keep the collection register live where required.
5. Non-reference registers do not pollute safepoint root sets.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_safepoints.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_liveness.py tests/compiler/backend/analysis/test_safepoints.py tests/compiler/backend/lowering/test_arrays.py tests/compiler/backend/lowering/test_backend_calls.py -q
```

### Expected Outcome

- GC-relevant liveness is computed from backend IR rather than semantic statements.
- The known loop-carried root-clearing risk is covered by CFG-based tests.
- Root-slot planning can consume one deterministic safepoint-live-register summary.

### Checklist

- [ ] Add `compiler/backend/analysis/safepoints.py`.
- [ ] Define safepoints from backend `effects` and call metadata only.
- [ ] Port or mirror the legacy root-liveness regression surface.
- [ ] Add explicit loop-carried reference coverage.

## PR 5: Named Root-Slot Planning From Backend Safepoint Liveness

### Goal

Replace legacy local-ID root-slot planning with backend-register root-slot planning driven by the safepoint live-reference sets from PR 4.

### Primary Files To Change

New files:

- `compiler/backend/analysis/root_slots.py`
- `tests/compiler/backend/analysis/test_root_slots.py`

Existing files:

- `compiler/backend/analysis/safepoints.py`
- [compiler/backend/ir/model.py](../compiler/backend/ir/model.py)
- [compiler/codegen/root_slot_plan.py](../compiler/codegen/root_slot_plan.py) as the migration reference for the deterministic coloring policy
- [tests/compiler/codegen/test_root_slot_plan.py](../tests/compiler/codegen/test_root_slot_plan.py) as the coverage set to port or mirror

### What To Change

1. Implement a root-slot planner keyed by `BackendRegId` rather than `LocalId`.
   The planner should only assign slots to reference-typed registers that are live at one or more safepoints.

2. Preserve deterministic slot assignment.
   Reuse the same broad policy that already works in the legacy backend unless phase-3 constraints force a better ordering:
   - build an interference relation from safepoint live sets
   - order registers deterministically by conflict pressure and stable first-use position
   - greedily reuse the first non-conflicting slot

3. Keep the plan target-neutral.
   This slice should compute slot indices only, not physical stack offsets or ABI details.

4. Verify that loop-carried references keep a stable slot across the whole loop body.
   The new planner must eliminate the need for the legacy "skip dead clears inside loop bodies" workaround on the correctness side.

5. Make the result easy to hand to later target code.
   `BackendFunctionAnalysisDump.root_slot_by_reg` is the natural debug shape for this slice.

### What To Test

1. Registers with no safepoint participation receive no slots.
2. Disjoint safepoint live ranges reuse one slot.
3. Overlapping live ranges receive distinct slots.
4. Loop-carried references keep one stable slot.
5. Slot assignment order is deterministic across runs.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_root_slots.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_safepoints.py tests/compiler/backend/analysis/test_root_slots.py tests/compiler/backend/lowering/test_arrays.py tests/compiler/backend/lowering/test_control_flow.py -q
```

### Expected Outcome

- Root-slot planning is driven by backend register liveness instead of semantic locals.
- Slot reuse and conflict behavior are deterministic and testable.
- The correctness side of root planning is ready for later target frame lowering.

### Checklist

- [ ] Add `compiler/backend/analysis/root_slots.py`.
- [ ] Build slot conflicts from backend safepoint live-register sets.
- [ ] Preserve deterministic slot reuse and stable loop-carried slots.
- [ ] Port or mirror the legacy root-slot planning regression coverage.

## PR 6: Stack-Home Planning For Backend Registers And Temporaries

### Goal

Plan symbolic stack homes for backend virtual registers and temporaries so later target emission can lower from backend IR without reopening legacy layout logic.

### Primary Files To Change

New files:

- `compiler/backend/analysis/stack_homes.py`
- `tests/compiler/backend/analysis/test_stack_homes.py`

Existing files:

- `compiler/backend/analysis/liveness.py`
- `compiler/backend/analysis/root_slots.py`
- [compiler/backend/ir/model.py](../compiler/backend/ir/model.py)
- [compiler/codegen/layout.py](../compiler/codegen/layout.py) as the migration reference for the current correctness surface
- [tests/compiler/codegen/test_layout.py](../tests/compiler/codegen/test_layout.py) as the coverage set to port or mirror

### What To Change

1. Introduce a target-neutral stack-home planner.
   This planner should assign deterministic symbolic home names to backend registers and any required temporaries without choosing concrete byte offsets yet.

2. Keep the home model simple.
   One acceptable phase-3 approach is:
   - every register that needs material storage receives one symbolic home
   - the planner exposes only a deterministic string identity per register
   - later target lowering maps those symbolic homes to concrete frame offsets
   Freeze the chosen naming convention in tests once selected.

3. Cover the current layout correctness surface, not just arguments.
   The planner should account for:
   - parameters and receiver registers
   - locals and synthetic temporaries
   - mixed control flow
   - double-typed values and call-heavy shapes that later need ABI-sensitive handling
   - constructor-specific receiver behavior where relevant

4. Keep root-slot planning separate.
   Stack homes and GC root slots are related but not identical. Do not fold the two maps together in this slice.

5. Use the legacy layout tests as migration guidance, not as a mandate to preserve old stack-offset math.
   Phase 3 only needs to preserve the observable planning invariants that later emission depends on.

### What To Test

1. Parameters, locals, and temporaries all receive deterministic symbolic homes when needed.
2. Distinct shadowed locals receive distinct homes.
3. `for in` helper temporaries and other synthetic registers are planned explicitly.
4. Mixed primitive or reference and double-valued shapes remain deterministic.
5. Constructor receiver and parameter cases are covered where storage differs from plain functions.

### How To Test

Focused command:

```text
pytest tests/compiler/backend/analysis/test_stack_homes.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/analysis/test_stack_homes.py tests/compiler/backend/analysis/test_root_slots.py tests/compiler/backend/lowering/test_arrays.py tests/compiler/backend/lowering/test_objects.py -q
```

### Expected Outcome

- Backend IR now has a target-neutral storage plan for registers and temporaries.
- Later target emission can consume symbolic homes instead of re-deriving layout from semantic trees.
- The current layout corner cases are represented in backend-analysis tests.

### Checklist

- [ ] Add `compiler/backend/analysis/stack_homes.py`.
- [ ] Assign deterministic symbolic homes to stored registers and temporaries.
- [ ] Keep root-slot and stack-home planning as separate maps.
- [ ] Port or mirror the relevant legacy layout regression coverage.

## PR 7: Deterministic Block Ordering, Backend Pass Pipeline, And Checked-Path `backend-ir-passes` Wiring

### Goal

Make phase 3 operational by packaging the new cleanup and analysis passes behind one explicit backend pipeline and wiring the reserved CLI phase boundary to the real pass sequence.

### Primary Files To Change

New files:

- `compiler/backend/analysis/block_order.py`
- `compiler/backend/analysis/pipeline.py`
- `tests/compiler/backend/analysis/test_block_order.py`
- `tests/compiler/integration/test_cli_backend_ir_passes.py`

Existing files:

- `compiler/backend/analysis/__init__.py`
- [compiler/cli.py](../compiler/cli.py)
- [compiler/backend/ir/text.py](../compiler/backend/ir/text.py)
- [compiler/backend/ir/serialize.py](../compiler/backend/ir/serialize.py)
- [tests/compiler/integration/test_cli_backend_ir_dump.py](../tests/compiler/integration/test_cli_backend_ir_dump.py)
- [tests/compiler/integration/test_cli_backend_ir_flags.py](../tests/compiler/integration/test_cli_backend_ir_flags.py)
- [tests/compiler/integration/test_cli_codegen.py](../tests/compiler/integration/test_cli_codegen.py)

### What To Change

1. Add deterministic block ordering in `compiler/backend/analysis/block_order.py`.
   The result should be suitable for later target emission and stable dumps.
   A reasonable default is a deterministic traversal from entry that keeps loop and branch structure readable.

2. Add `compiler/backend/analysis/pipeline.py` with one explicit program-level entrypoint.
   The intended surface for this phase is something like:

   ```python
   run_backend_ir_pipeline(program: BackendProgram) -> BackendProgram
   ```

   That pipeline should, in order:
   - verify the phase-2 lowered input if the caller has not already done so
   - run CFG cleanup
   - recompute CFG indexes
   - run liveness, safepoints, root-slot planning, stack-home planning, and block ordering
   - return a verified backend program plus analysis results that later targets can consume

3. Keep the core IR serialization contract stable.
   `--stop-after backend-ir-passes` may dump the post-pass backend IR itself. Do not require optional analysis-dump sections unless they are truly needed to make the output useful.

4. Wire `compiler/cli.py` to make `--stop-after backend-ir-passes` real.
   The checked path should:
   - lower to backend IR once
   - run the phase-3 backend pass pipeline once
   - dump or print the post-pass backend IR in text or JSON
   - continue to reject incompatible flag combinations deterministically

5. Keep the normal assembly path unchanged.
   Even after `backend-ir-passes` exists, default checked compilation must still use the legacy backend unless the user explicitly requests a backend-IR phase boundary.

### What To Test

1. Block order is deterministic for branches and loops.
2. The pipeline runs all required phase-3 passes in a stable order.
3. `--stop-after backend-ir-passes` succeeds on real programs and prints or writes the post-pass IR.
4. Existing `backend-ir` dump behavior remains intact.
5. The default checked codegen path remains unchanged when backend-IR flags are absent.

### How To Test

Focused commands:

```text
pytest tests/compiler/backend/analysis/test_block_order.py -q
pytest tests/compiler/integration/test_cli_backend_ir_passes.py -q
```

Recommended gate command for this slice:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering tests/compiler/backend/analysis tests/compiler/backend/ir tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_backend_ir_passes.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

### Expected Outcome

- Phase 3 has one real backend pass pipeline, not just isolated pass helpers.
- `backend-ir-passes` becomes a usable, checked-path debugging seam.
- The repository has a complete correctness-oriented backend-analysis layer ready for the phase-4 target bring-up.

### Checklist

- [ ] Add `compiler/backend/analysis/block_order.py`.
- [ ] Add `compiler/backend/analysis/pipeline.py`.
- [ ] Wire `--stop-after backend-ir-passes` to the real pass pipeline.
- [ ] Add CLI integration coverage for post-pass backend IR dumps.
- [ ] Re-run existing CLI coverage to prove default checked codegen is unchanged.

## Phase 3 Gate Checklist

Use this checklist when phase 3 is believed to be complete.

- [ ] `compiler/backend/analysis/` exposes stable CFG indexing utilities.
- [ ] Unreachable-block elimination and basic CFG simplification run on backend IR callables.
- [ ] Virtual-register liveness is computed from backend CFG, not semantic statements.
- [ ] Safepoint live-reference sets are computed from backend effects and register types.
- [ ] Loop-carried reference regressions pass without relying on the legacy loop-clearing workaround.
- [ ] Root-slot planning is driven by backend-register safepoint liveness.
- [ ] Stack-home planning exists for backend registers and temporaries.
- [ ] Deterministic block ordering exists for later target emission.
- [ ] `--stop-after backend-ir-passes` works on the checked CLI path.
- [ ] The default checked assembly path remains unchanged when backend-IR flags are not used.

Recommended phase gate command:

```text
pytest -n auto --dist loadfile tests/compiler/backend/lowering tests/compiler/backend/analysis tests/compiler/backend/ir tests/compiler/integration/test_cli_backend_ir_dump.py tests/compiler/integration/test_cli_backend_ir_flags.py tests/compiler/integration/test_cli_backend_ir_passes.py tests/compiler/integration/test_cli_codegen.py tests/compiler/integration/test_cli_errors.py -q
```

Expected phase gate outcome:

- all new backend analysis tests pass
- backend IR cleanup and analysis passes run on real lowered programs
- `--stop-after backend-ir-passes` provides a usable checked-path debug seam
- the legacy checked assembly path remains unchanged until phase 4 or later