# x86_64 SysV Register Allocation Plan

Status: proposed.

This document describes a staged implementation plan for adding register allocation to the `x86_64_sysv` backend.

The plan treats register allocation as target-specific lowering and planning, not as a target-independent backend IR optimization. The generic backend IR should remain virtual-register based. The x86_64 SysV backend should consume the existing backend IR analyses, build a target-specific callable plan, and emit assembly from that plan.

## Goals

1. Reduce unnecessary stack traffic in generated x86_64 SysV assembly.
2. Keep backend IR target-independent and easy to dump, verify, and optimize.
3. Preserve GC root correctness at safepoints.
4. Make each implementation slice small enough to test and review independently.
5. Keep the first allocator deliberately conservative, then broaden it once the shape is proven.

## Non-Goals

1. Do not convert backend IR to SSA in this plan.
2. Do not add graph-coloring register allocation in the first implementation.
3. Do not make register allocation part of `compiler/backend/optimizations`.
4. Do not remove stack homes until allocation-aware emission is stable.
5. Do not require every backend virtual register to receive a physical register.

## Design Rules

Use these rules throughout the implementation:

1. Keep the backend IR model unchanged unless a later slice finds a verifier or dump limitation that directly blocks allocation.
2. Keep target-independent analyses in `compiler/backend/analysis`.
3. Put x86_64-specific allocation data, register classes, ABI constraints, and frame changes under `compiler/backend/targets/x86_64_sysv`.
4. Prefer sidecar planning data over mutating backend IR into target-specific IR.
5. Preserve the existing stack-home path as the fallback for spills and unsupported allocation cases.
6. Emit deterministic assembly. Allocation order, spill choices, and debug comments must not depend on hash iteration.
7. Add focused unit tests for planning logic before relying on golden end-to-end coverage.
8. Keep GC root sync/reload behavior correct for stack-resident and physical-register-resident values.
9. Keep the first allocator simple: linear scan with conservative physical-register pools.
10. Update this document's checkboxes as implementation lands.

## Target Architecture

The new target planning layer should sit between `BackendTargetInput.from_pipeline_result(...)` and assembly emission.

Current broad shape:

```text
backend IR
  -> backend IR optimization pipeline
  -> backend IR analysis pipeline
  -> x86_64_sysv assembly emission
```

Planned broad shape:

```text
backend IR
  -> backend IR optimization pipeline
  -> backend IR analysis pipeline
  -> x86_64_sysv target planning
       -> register classification
       -> live interval construction
       -> register allocation
       -> frame layout planning
  -> x86_64_sysv assembly emission from target plans
```

Recommended new files:

- `compiler/backend/targets/x86_64_sysv/locations.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/pipeline.py`

Expected existing files to change:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/root_codegen.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`

Expected test files:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_locations.py` if location helpers grow enough behavior to deserve their own file
- `tests/compiler/backend/targets/x86_64_sysv/test_frame.py`
- existing x86_64 SysV emission tests under `tests/compiler/backend/targets/x86_64_sysv/`
- selected golden specs under `tests/golden/`

## Core Data Model

The implementation should introduce explicit target-side locations instead of passing raw strings through emission code.

Suggested data shapes:

```python
@dataclass(frozen=True, slots=True)
class X86_64SysVPhysicalRegister:
    name: str
    byte_name: str | None
    register_class: X86_64SysVRegisterClass
    preserved_by_callee: bool


@dataclass(frozen=True, slots=True)
class X86_64SysVStackLocation:
    byte_offset: int
    debug_name: str


@dataclass(frozen=True, slots=True)
class X86_64SysVRegisterLocation:
    reg_id: BackendRegId
    physical_register: X86_64SysVPhysicalRegister | None
    stack_slot: X86_64SysVStackLocation | None
```

Use a single allocation result as the source of truth:

```python
@dataclass(frozen=True, slots=True)
class X86_64SysVRegisterAllocation:
    callable_decl: BackendCallableDecl
    location_by_reg: dict[BackendRegId, X86_64SysVRegisterLocation]
    used_callee_saved_registers: tuple[X86_64SysVPhysicalRegister, ...]
    spilled_reg_ids: tuple[BackendRegId, ...]
```

Use a callable plan to connect allocation, frame layout, and existing analysis:

```python
@dataclass(frozen=True, slots=True)
class X86_64SysVCallablePlan:
    callable_decl: BackendCallableDecl
    analysis: BackendPipelineCallableAnalysis
    allocation: X86_64SysVRegisterAllocation
    frame_layout: X86_64SysVFrameLayout
    ordered_block_ids: tuple[BackendBlockId, ...]
```

## Ordered Implementation Checklist

1. [x] Slice 1: Add target location and register-class model.
2. [x] Slice 2: Add target planning pipeline shell.
3. [x] Slice 3: Build deterministic live intervals.
4. [x] Slice 4: Implement conservative linear-scan allocation.
5. [x] Slice 5: Thread allocation into frame layout.
6. [x] Slice 6: Make scalar instruction selection allocation-aware.
7. [x] Slice 7: Preserve GC root correctness for physical locations.
8. [x] Slice 8: Make call lowering allocation-aware.
9. [ ] Slice 9: Enable allocation behind an internal target option.
10. [ ] Slice 10: Broaden allocation coverage and remove the temporary option if stable.

## Slice 1: Target Location And Register-Class Model

### Goal

Create small, explicit data structures for x86_64 physical registers, stack locations, and backend-register locations. No assembly output should change in this slice.

### Where

New files:

- `compiler/backend/targets/x86_64_sysv/locations.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_locations.py`

### What To Do

1. Add a register class enum or literal type for `gpr` and `xmm`.
2. Define x86_64 physical-register metadata:
   - full register name
   - byte register name when needed
   - register class
   - caller-saved or callee-saved status
3. Expose named register pools from `abi.py` or `locations.py`:
   - conservative allocatable GPRs for slice 4: `rbx`, `r12`, `r13`, `r14`, `r15`
   - later caller-saved GPR candidates: `rax`, `rcx`, `rdx`, `rsi`, `rdi`, `r8`, `r9`, `r10`, `r11`
   - later XMM candidates: `xmm0` through `xmm15`
4. Keep scratch registers named in instruction selection separate from allocatable pools until later slices explicitly merge them.
5. Add helper functions for classifying backend register types:
   - `double` maps to `xmm`
   - all current integer, bool, callable, object, array, string, interface, and null-compatible references map to `gpr`

### Checklist

- [x] Add physical register metadata.
- [x] Add register class classification helper.
- [x] Add conservative allocatable GPR pool.
- [x] Add tests for register metadata and type classification.
- [x] Confirm no assembly snapshots change.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_locations.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
```

## Slice 2: Target Planning Pipeline Shell

### Goal

Introduce a target-specific planning layer that can later hold allocation and frame decisions without forcing allocation into the generic backend analysis pipeline.

### Where

New files:

- `compiler/backend/targets/x86_64_sysv/pipeline.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/__init__.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_frame.py`

### What To Do

1. Add `X86_64SysVCallablePlan`.
2. Add `X86_64SysVTargetPlan` for whole-program target planning:
   - target input
   - callable plan by callable ID
   - diagnostics if needed later
3. Add `plan_x86_64_sysv_target(target_input, options=...)`.
4. In this slice, build plans with the existing all-stack frame layout.
5. Update `emit.py` to consume callable plans internally while preserving the public `emit_x86_64_sysv_asm(...)` API.
6. Keep `BackendTargetInput` unchanged.

### Checklist

- [x] Add target plan dataclasses.
- [x] Build one callable plan per non-extern callable.
- [x] Keep extern callables out of frame/allocation planning.
- [x] Route `emit.py` through the target plan.
- [x] Preserve existing output exactly or explain any deterministic debug-comment-only changes.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv -q
pytest tests/compiler/integration/test_cli_codegen.py -q
```

## Slice 3: Deterministic Live Intervals

### Goal

Build deterministic live intervals from the existing backend liveness analysis and ordered blocks. This slice should still not change emitted assembly.

### Where

New files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`

Existing files:

- `compiler/backend/targets/x86_64_sysv/pipeline.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Add an internal instruction-position numbering scheme:
   - positions must follow `ordered_block_ids`
   - each instruction gets a stable position
   - each terminator gets a stable position if terminator uses matter
2. Build live intervals for every backend virtual register:
   - start at first definition or first live-in use
   - end at last use or last live-out position
   - include parameter and receiver registers as live from callable entry
3. Record useful interval metadata:
   - register class
   - whether the interval crosses a call
   - whether the register is a GC reference
   - whether the interval is live at a safepoint
4. Sort intervals deterministically by start position, end position, then backend register ID.
5. Add test fixtures with straight-line code, branches, loops, calls, and safepoints.

### Checklist

- [x] Add position numbering.
- [x] Add live interval builder.
- [x] Mark call-crossing intervals.
- [x] Mark safepoint-live intervals.
- [x] Add unit tests for straight-line and control-flow intervals.
- [x] Add unit tests for call-crossing intervals.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/analysis/test_liveness.py -q
```

If there is no dedicated liveness test file yet, run the existing backend analysis test slice:

```text
pytest tests/compiler/backend -q
```

## Slice 4: Conservative Linear-Scan Allocation

### Goal

Allocate a small, safe subset of backend virtual registers to physical registers. Spill everything else to the existing stack-home model.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/pipeline.py`
- `compiler/backend/targets/x86_64_sysv/locations.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Implement linear scan over sorted intervals.
2. For the first allocator version, use only callee-saved GPRs:
   - `rbx`
   - `r12`
   - `r13`
   - `r14`
   - `r15`
3. Spill all XMM intervals.
4. Spill intervals that cannot be represented safely yet.
5. Prefer allocating long-lived non-float scalar intervals only when this is easy to reason about.
6. Use deterministic spill choice:
   - expire intervals by end position
   - when a register is needed, spill the active interval with the farthest end position if that improves the current interval
   - break ties by backend register ID
7. Return `X86_64SysVRegisterAllocation`.
8. Add debug-friendly summaries for tests and optional comments.

### Checklist

- [x] Implement active-set expiration.
- [x] Implement physical register assignment.
- [x] Implement deterministic spill choice.
- [x] Spill unsupported register classes.
- [x] Track used callee-saved registers.
- [x] Add unit tests for no-pressure, pressure, and spill cases.
- [x] Add unit tests for deterministic tie-breaking.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
```

## Slice 5: Allocation-Aware Frame Layout

### Goal

Teach frame planning about allocated physical registers while preserving stack slots for spilled values, parameters, safepoints, and fallback emission.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/pipeline.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_frame.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`

### What To Do

1. Extend `X86_64SysVFrameLayout` with:
   - allocation
   - used callee-saved registers
   - spill slots
   - optional all-stack fallback slots while migration is incomplete
2. Reserve stack space to save used callee-saved registers.
3. Emit callee-saved saves in the prologue and restores in the epilogue.
4. Keep stack alignment correct after adding callee-saved save slots.
5. Continue reserving outgoing stack-argument space as before.
6. Continue reserving root-frame and root-slot space as before.
7. Keep parameter spilling behavior unchanged in this slice unless all emission paths can already read initial parameter locations.

### Checklist

- [x] Extend frame layout dataclasses.
- [x] Add used callee-saved save/restore planning.
- [x] Update stack-size calculation.
- [x] Emit callee-saved saves in the prologue.
- [x] Emit callee-saved restores in the epilogue.
- [x] Preserve stack alignment tests.
- [x] Preserve existing call stack-reservation behavior.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_frame.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
```

## Slice 6: Allocation-Aware Scalar Instruction Selection

### Goal

Allow ordinary scalar instruction emission to read allocated source registers and write allocated destination registers, falling back to stack homes for spills.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Add helpers for resolving a backend register to its current target location.
2. Update `emit_load_operand(...)`:
   - if the source vreg is physical, load from that physical register
   - if the source vreg is spilled, load from the stack slot
3. Update `emit_store_result(...)`:
   - if the destination vreg is physical, move from the computation scratch register into that physical register
   - if the destination vreg is spilled, store to the stack slot
4. Keep the existing scratch-register computation discipline:
   - `rax` remains primary integer scratch
   - `rcx` remains secondary integer scratch
   - `xmm0` and `xmm1` remain float scratch registers
5. Do not allocate scratch registers in the first allocator pool.
6. Add debug comments under `emit_debug_comments` that show physical assignments.

### Checklist

- [x] Add location resolution helpers.
- [x] Make integer loads allocation-aware.
- [x] Make integer stores allocation-aware.
- [x] Keep bool normalization correct for physical and stack sources.
- [x] Preserve float fallback behavior.
- [x] Add assembly tests that prove stack load/store counts decrease in simple scalar code.
- [x] Add tests that spilled values still use stack homes.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
```

## Slice 7: GC Root Correctness For Physical Locations

### Goal

Keep safepoint root synchronization correct when GC references are allocated to physical registers.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/root_codegen.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- selected runtime golden tests under `tests/golden/runtime/`

### What To Do

1. Decide the first-slice reference policy:
   - simplest safe policy: spill all GC-reference registers
   - better policy: allow physical reference registers and teach root sync/reload to copy from or to the physical register
   Chosen policy: allow physical reference registers; root sync copies from the physical register when present, and root reload restores both the physical register and the stack home.
2. If references can be physical, update `emit_root_slot_sync(...)`:
   - physical source: copy physical register to root slot
   - stack source: copy stack home to root slot as today
3. If references can be physical, update `emit_root_slot_reload(...)`:
   - physical destination: reload root slot into physical register
   - stack destination: reload root slot into stack home as today
4. Preserve root-slot coalescing from existing backend analysis.
5. Add tests for object references live across allocation calls, runtime calls, and trace safepoints.
6. Keep root sync/reload deterministic and easy to inspect in debug assembly.

### Checklist

- [x] Choose and document the initial reference allocation policy.
- [x] Update root sync for physical source locations or spill all references.
- [x] Update root reload for physical destination locations or spill all references.
- [x] Add tests for physical or deliberately-spilled references at safepoints.
- [x] Run runtime-root emission tests.
- [x] Run selected GC/runtime golden tests.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
./scripts/golden.sh --filter 'runtime/**'
```

## Slice 8: Allocation-Aware Call Lowering

### Goal

Make function, method, constructor, runtime, indirect, virtual, and interface call lowering work correctly when arguments, receivers, callees, and return destinations may live in physical registers.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`

### What To Do

1. Ensure call argument loading reads physical and stack source locations correctly.
2. Ensure indirect call target loading reads physical and stack source locations correctly.
3. Ensure return-value storage writes to physical and stack destination locations correctly.
4. Keep the first allocator using only callee-saved GPRs so call clobber handling remains simple.
5. Verify caller-saved scratch registers used by call lowering are not in the first allocatable pool.
6. Add tests for:
   - register arguments
   - stack arguments
   - receiver calls
   - indirect calls
   - calls returning into physical locations
   - live allocated values across calls

### Checklist

- [x] Make argument loading allocation-aware.
- [x] Make indirect call target loading allocation-aware.
- [x] Make call return storage allocation-aware.
- [x] Prove callee-saved allocated values survive calls.
- [x] Preserve receiver null-check behavior.
- [x] Preserve runtime trace location hooks.
- [x] Preserve safepoint preamble and postamble behavior.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_objects.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_arrays.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
```

## Slice 9: Enable Allocation Behind An Internal Target Option

### Goal

Run the allocation-aware path in normal tests while retaining a short-lived fallback switch for debugging regressions during rollout.

### Where

Existing files:

- `compiler/backend/targets/api.py`
- `compiler/backend/targets/x86_64_sysv/pipeline.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/cli.py` only if a CLI-visible debug flag is intentionally added

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/`
- `tests/compiler/integration/`
- `tests/golden/`

### What To Do

1. Add an internal option such as `register_allocation_enabled`.
   - Implemented as `BackendTargetOptions.register_allocation_enabled`, defaulting to enabled.
2. Default the option to enabled only after slices 5 through 8 pass targeted tests.
   - Slices 5 through 8 have focused coverage, so the normal x86_64 SysV path now allocates registers.
3. Keep the disabled path as the old all-stack behavior for one or two follow-up slices.
   - Passing `BackendTargetOptions(register_allocation_enabled=False)` returns the preliminary all-stack plan.
4. Avoid adding a public CLI flag unless debugging experience shows it is needed.
   - No CLI flag was added for this internal rollout switch.
5. If a CLI flag is added, document it as temporary and testing-oriented.
6. Record assembly-size and instruction-count observations for representative samples.
   - A scalar sample now has distinct allocated and all-stack assembly in tests; the allocated path emits physical-register moves and callee-saved saves where needed, while the disabled path reloads from stack homes.

### Checklist

- [x] Add internal target option.
- [x] Keep all-stack fallback.
- [x] Default allocation on after focused tests are green.
- [x] Add tests for both enabled and disabled paths where practical.
- [x] Measure representative assembly output.
- [ ] Decide when the fallback can be removed.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv -q
pytest tests/compiler/integration -q
./scripts/golden.sh --filter 'arithmetic/**'
./scripts/golden.sh --filter 'std/math/**'
```

## Slice 10: Broaden Coverage And Retire Temporary Fallbacks

### Goal

Expand register allocation beyond the conservative first slice and remove temporary migration switches once the path is stable.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/locations.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/api.py`
- `compiler/cli.py` if a temporary debug flag was added

Tests:

- full backend target suite
- full integration suite
- full golden suite

### What To Do

1. Consider allocating short-lived values into caller-saved GPRs.
2. Add call-clobber handling before using caller-saved registers for values live across calls.
3. Consider XMM allocation for double values.
4. Add explicit spill/reload insertion or split intervals if caller-saved and XMM allocation need it.
5. Add copy coalescing only after the basic allocator is stable.
6. Remove the temporary all-stack fallback option once it no longer catches useful regressions.
7. Update docs to describe register allocation as part of the normal x86_64 SysV target backend.

### Checklist

- [ ] Evaluate caller-saved GPR allocation.
- [ ] Add call-clobber handling if caller-saved registers are used.
- [ ] Evaluate XMM allocation.
- [ ] Add interval splitting if needed.
- [ ] Add copy coalescing only if tests show clear value.
- [ ] Remove temporary fallback switches.
- [ ] Update repository docs.
- [ ] Run the full validation gate.

### How To Test

Focused tests:

```text
pytest tests/compiler/backend/targets/x86_64_sysv -q
pytest tests/compiler/integration -q
```

Golden tests:

```text
./scripts/golden.sh
```

Recommended full gate:

```text
pytest -n auto --dist loadfile tests/compiler tests/runtime -q
./scripts/golden.sh
```

## Correctness Risks And Mitigations

### Stack Alignment

Risk: saving callee-saved registers and changing frame size may break SysV stack alignment.

Mitigation:

- keep all frame sizing in `frame.py`
- add tests for functions with no calls, register-only calls, and outgoing stack-argument calls
- assert final stack size is ABI-aligned

### Scratch Register Conflicts

Risk: allocated physical registers may overlap fixed scratch registers used by instruction selection or call lowering.

Mitigation:

- do not allocate scratch registers in the first pool
- represent scratch and allocatable pools explicitly
- add tests that inspect emitted assembly for allocated registers and scratch registers

### GC Root Sync

Risk: live references in physical registers may not be visible to the runtime GC at safepoints.

Mitigation:

- spill references in the first version or make root sync/reload location-aware before allocating references
- test allocation and runtime-call safepoints
- keep root slot planning target-independent and only change target sync emission

### Call Clobbers

Risk: values in caller-saved registers may be overwritten by calls.

Mitigation:

- allocate only callee-saved GPRs at first
- mark call-crossing intervals in live interval metadata
- add caller-saved allocation only after call-clobber handling exists

### Debuggability

Risk: assembly becomes harder to understand if register decisions are implicit.

Mitigation:

- expose allocation summaries in unit tests
- add optional debug comments for physical locations and spills
- keep stack home names stable for spilled values

## Completion Criteria

This plan is complete when:

1. `x86_64_sysv` has a target planning layer that owns register allocation and frame layout.
2. The allocator assigns at least some scalar backend virtual registers to physical registers in normal checked compilation.
3. Spilled values continue to use stack homes correctly.
4. Callee-saved registers used by allocation are saved and restored correctly.
5. Calls, control flow, returns, and GC safepoints remain correct.
6. Focused allocator tests, x86_64 SysV backend tests, integration tests, and golden tests pass.
7. Temporary rollout flags or fallback paths are either removed or documented as intentional debugging tools.
