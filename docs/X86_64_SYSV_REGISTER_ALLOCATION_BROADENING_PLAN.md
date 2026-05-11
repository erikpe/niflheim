# x86_64 SysV Register Allocation Broadening Plan

Status: proposed.

This document describes the next register-allocation phase for the `x86_64_sysv` backend.

The first register-allocation plan deliberately proved the target-planning shape with a conservative allocator: callee-saved GPRs only, stack homes preserved, simple coalescing, and small instruction-selection cleanup. This plan broadens that allocator so the backend can harvest the performance benefits enabled by physical locations.

## Goals

1. Reduce total emitted instruction count, not only stack-memory instruction count.
2. Allocate caller-saved GPRs where they are profitable and ABI-safe.
3. Allocate XMM registers for `double` values and double operations.
4. Split intervals broadly enough to avoid avoidable spills and avoid pinning values in expensive locations.
5. Improve global copy coalescing, especially around calls, returns, and argument setup.
6. Make ABI boundaries explicit in allocation so instruction selection and call lowering can avoid needless register shuttling.
7. Preserve GC root correctness at safepoints.
8. Keep the implementation deterministic, readable, and testable slice by slice.

## Non-Goals

1. Do not replace linear scan with graph coloring in this plan.
2. Do not make register allocation a target-independent backend optimization.
3. Do not remove all stack homes until root/debug/fallback behavior no longer needs them.
4. Do not allocate registers across safepoints in a way that hides GC references from root synchronization.
5. Do not optimize by adding broad text-level assembly rewrites. Peephole cleanup remains a small safety net only.

## Current Baseline

The current allocator:

- Allocates conservative callee-saved GPRs: `rbx`, `r12`, `r13`, `r14`, `r15`.
- Spills XMM intervals to stack.
- Preserves stack homes and suppresses some unnecessary home writes.
- Performs simple dead-at-copy coalescing.
- Uses a tiny post-emission peephole pass.

Representative measurement after the conservative cleanup phase:

```text
source: tests/golden/aoc/2025/10/part2/test_solver.nif
command: /bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace

metric                          without_ra  with_ra  delta
instruction_count                    16368    17127   +759
stack_memory_instruction_count        8417     5871  -2546
stack_load_count                      4424     2534  -1890
stack_store_count                     3720     3009   -711
register_copy_count                    284     3784  +3500
callee_saved_save_count                  0      424   +424
callee_saved_restore_count               0      424   +424
```

The broadening phase should reduce `register_copy_count`, reduce unnecessary callee-saved save/restore pressure, and begin converting the stack-memory reduction into a real total-instruction reduction.

## Design Rules

1. Keep backend IR virtual-register based.
2. Put target-specific allocation decisions under `compiler/backend/targets/x86_64_sysv`.
3. Prefer explicit target-plan metadata over implicit emission heuristics.
4. Model ABI clobbers and fixed registers before allocating caller-saved registers.
5. Keep every slice correct with GC roots and runtime calls before chasing larger wins.
6. Keep all allocation ordering deterministic.
7. Add focused allocator tests before relying on golden coverage.
8. Measure representative samples after every performance-oriented slice.

## Implementation Slices

1. [x] Slice 1: Add explicit ABI interference and fixed-register constraints.
2. [x] Slice 2: Allocate caller-saved GPRs for call-free intervals.
3. [ ] Slice 3: Allocate caller-saved GPRs across calls with targeted spill/reload.
4. [ ] Slice 4: Make argument setup allocation-aware enough to avoid avoidable moves.
5. [ ] Slice 5: Make return-value placement and return coalescing ABI-aware.
6. [ ] Slice 6: Allocate XMM registers for `double` intervals.
7. [ ] Slice 7: Make double instruction selection and call lowering XMM-location aware.
8. [ ] Slice 8: Add global copy coalescing with conservative interference checks.
9. [ ] Slice 9: Add interval splitting at ABI boundaries and high-pressure regions.
10. [ ] Slice 10: Add rematerialization for cheap constants and addresses.
11. [ ] Slice 11: Reduce stack-home traffic and callee-saved save/restore cost.
12. [ ] Slice 12: Improve measurement, regression gates, and allocation diagnostics.

## Slice 1: Add Explicit ABI Interference And Fixed-Register Constraints

### Goal

Teach allocation about registers that are fixed, clobbered, or required by the ABI before allocating caller-saved or XMM registers more broadly.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/locations.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/pipeline.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_abi.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_locations.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Add target-plan metadata for fixed register uses.
   - integer return: `rax`
   - float return: `xmm0`
   - integer arguments: `rdi`, `rsi`, `rdx`, `rcx`, `r8`, `r9`
   - float arguments: `xmm0` through `xmm7`
   - shift count: `rcx`/`cl`
   - division/remainder: `rax`/`rdx`
   - scratch registers used by runtime/root/codegen helpers
2. Add call-clobber sets for SysV caller-saved GPR and XMM registers.
3. Represent fixed-register constraints as sidecar allocation constraints, not backend IR mutations.
4. Make tests assert constraints are deterministic and visible to the allocator.

### Checklist

- [x] Add fixed-register constraint model.
- [x] Add caller-saved GPR clobber metadata.
- [x] Add caller-saved XMM clobber metadata.
- [x] Model special instruction constraints for shift and division.
- [x] Add allocator tests for constraint collection.
- [x] Preserve current conservative allocation behavior.

### Implementation Notes

The allocator now records ABI/fixed-register constraints as sidecar metadata on `X86_64SysVRegisterAllocation`.

This slice intentionally does not change placement decisions. The metadata covers incoming arguments, call arguments, call returns, caller-saved clobbers, return values, shift count use of `rcx/cl`, division use of `rax/rdx`, and current call-lowering scratch registers. Later slices can consume the metadata to safely broaden physical-register pools.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_abi.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_locations.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
```

## Slice 2: Allocate Caller-Saved GPRs For Call-Free Intervals

### Goal

Use caller-saved GPRs for intervals that do not cross calls or safepoints, reducing callee-saved save/restore cost and increasing available GPR capacity.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/locations.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`

### What To Do

1. Add a caller-saved GPR allocation pool.
2. Prefer caller-saved GPRs for intervals that:
   - do not cross calls
   - do not cross safepoints requiring root sync
   - do not have fixed-register conflicts
3. Keep callee-saved GPRs available for long-lived values, call-crossing values, and references where useful.
4. Ensure caller-saved registers do not create callee-saved frame slots.
5. Measure callee-saved save/restore reductions.

### Checklist

- [x] Add caller-saved GPR pool.
- [x] Allocate call-free scalar intervals into caller-saved GPRs.
- [x] Preserve call-crossing conservative behavior.
- [x] Avoid callee-saved frame slots for caller-saved assignments.
- [x] Add focused allocation and emission tests.
- [x] Measure representative assembly statistics.

### Implementation Notes

The allocator now has a small call-free caller-saved pool: `r10`, `r11`.

This slice intentionally avoids `rax`, `rcx`, `rdx`, argument registers, and other caller-saved registers that still have broader fixed-register or lowering-scratch interactions. Caller-saved allocation is limited to GPR intervals that do not cross calls, do not overlap call clobbers or call argument/return constraints, are not live at safepoints, and are not GC references.

Entry physical-register loads now happen after runtime trace/root setup calls so caller-saved entry values are not clobbered before the first backend block.

### Observed Measurement

Command:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

After this slice:

```text
metric                          without_ra  with_ra  delta
instruction_count                    16368    17048   +680
stack_memory_instruction_count        8417     5692  -2725
stack_load_count                      4424     2427  -1997
stack_store_count                     3720     2948   -772
register_copy_count                    284     3875  +3591
callee_saved_save_count                  0      377   +377
callee_saved_restore_count               0      377   +377
```

Compared with the conservative cleanup baseline, emitted lines improved from `19256` to `19177`. Callee-saved save/restore counts improved from `424` each to `377` each.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

## Slice 3: Allocate Caller-Saved GPRs Across Calls With Targeted Spill/Reload

### Goal

Allow caller-saved GPR allocation for values that cross calls when the allocator can insert or request minimal spill/reload around the call.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`

Possible new file:

- `compiler/backend/targets/x86_64_sysv/save_restore.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`

### What To Do

1. Compute live caller-saved physical registers at each call.
2. Emit save/reload only for caller-saved physical registers live across that call.
3. Reuse stack homes or dedicated spill slots deterministically.
4. Preserve root synchronization for live references before safepoints.
5. Compare cost against using a callee-saved register for the whole interval.

### Checklist

- [x] Compute live caller-saved assignments per call.
- [x] Emit targeted save/reload around ordinary calls.
- [x] Emit targeted save/reload around runtime calls.
- [x] Preserve GC root sync and reload behavior.
- [x] Avoid saving registers whose value dies at the call.
- [x] Add execution tests for values live across calls.
- [x] Measure instruction and stack-memory tradeoffs.

### Implementation Notes

- Added per-call caller-saved spill metadata to `X86_64SysVRegisterAllocation`.
- Allowed non-reference GPR intervals that cross exactly one modeled call, and no extra safepointing helper instruction, to use the call-free caller-saved pool.
- Kept multi-call-crossing values and values crossing non-call helper safepoints in callee-saved registers as a simple cost heuristic: two save/reload instructions for one call roughly matches one callee-saved save/restore pair, while more calls usually lose.
- Saved caller-saved values to their existing stack homes before runtime trace hooks, safepoint hooks, argument setup, and the call itself.
- Reloaded saved values before call setup when trace/root hooks may have clobbered them, then reloaded again after the call.
- Left GC references out of caller-saved cross-call allocation so root synchronization remains responsible for reference liveness.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    16368    17131   +763
stack_memory_instruction_count        8417     5708  -2709
stack_load_count                      4424     2443  -1981
stack_store_count                     3720     2958   -762
register_copy_count                    284     3931  +3647
callee_saved_save_count                  0      376   +376
callee_saved_restore_count               0      376   +376
```

Compared with slice 2, callee-saved save/restore counts improved from `377` each to `376` each. Stack memory instructions rose from `5692` to `5708` after tightening the eligibility guard for non-call helper safepoints. Total instructions increased from `17048` to `17131` because the one-call save/reload pairs add local traffic; later coalescing and argument-boundary cleanup slices should recover some of that.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
./scripts/golden.sh --filter 'arithmetic/**'
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

## Slice 4: Make Argument Setup Allocation-Aware

### Goal

Reduce copies before calls by assigning or coalescing argument-producing intervals into their ABI argument registers when profitable.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/abi.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Collect argument-register preferences for each call operand.
2. Coalesce call argument values into `rdi`/`rsi`/`rdx`/`rcx`/`r8`/`r9` when:
   - the value dies at the call, or
   - the chosen physical register remains legal through the next use
3. Preserve move ordering for cycles and overlapping argument moves.
4. Keep stack-passed arguments unchanged except where existing stack homes can be reused safely.
5. Add call-shape tests with mixed register and stack arguments.

### Checklist

- [x] Collect call argument register preferences.
- [x] Coalesce dead-at-call arguments into ABI GPRs.
- [x] Handle overlapping argument moves deterministically.
- [x] Preserve stack argument behavior.
- [x] Add focused call-lowering tests.
- [x] Measure register-copy count around calls.

### Implementation Notes

- Added an explicit ABI argument GPR pool: `rdi`, `rsi`, `rdx`, `rcx`, `r8`, and `r9`.
- Added call-argument preferences for non-reference GPR operands that die at the call.
- Recorded call-argument reload metadata for values assigned directly to their ABI argument register.
- Saved coalesced argument registers to their stack homes before runtime trace/root hooks when those hooks can clobber the register.
- Forced call argument setup to reload those values from the stack home after hooks, preserving correctness while still removing ordinary register-to-register argument moves when no hook intervenes.
- Kept stack-passed arguments unchanged.
- Rejected argument-register coalescing for values live across non-call safepoint helpers, such as object allocation before constructor initialization.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    16368    17159   +791
stack_memory_instruction_count        8417     5712  -2705
stack_load_count                      4424     2431  -1993
stack_store_count                     3720     2976   -744
register_copy_count                    284     3953  +3669
callee_saved_save_count                  0      368   +368
callee_saved_restore_count               0      368   +368
```

Compared with slice 3, callee-saved save/restore counts improved from `376` each to `368` each. Total instructions rose from `17131` to `17159`; this slice trades some extra stack-home sync around instrumented calls for fewer callee-saved allocations and fewer ordinary argument-register copies. Later coalescing and trace-aware cleanup can make that tradeoff sharper.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
./scripts/golden.sh --filter 'aoc/2025/10/part2/**'
```

## Slice 5: Make Return-Value Placement ABI-Aware

### Goal

Reduce `rax <-> allocated-register` and `xmm0 <-> allocated-register` traffic around returns and call results.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py`

### What To Do

1. Add return-register preferences for values returned directly.
2. Add call-result preferences for values consumed immediately or returned immediately.
3. Avoid storing a call result into an allocated register only to move it back to `rax` or `xmm0`.
4. Preserve runtime trace epilogue behavior that temporarily saves return values.
5. Add tests for immediate return of calls, arithmetic results, and double results.

### Checklist

- [x] Collect return-register preferences.
- [x] Coalesce direct scalar returns with `rax`.
- [x] Coalesce direct double returns with `xmm0`.
- [x] Reduce call-result-to-return copies.
- [x] Preserve trace epilogue return preservation.
- [x] Add focused emission and execution tests.
- [x] Measure register-copy count around returns.

### Implementation Notes

- Added an explicit return-only GPR pool containing `rax`.
- Added return-register preferences for GPR intervals returned directly.
- Chose `rax` before ordinary caller-saved/callee-saved pools for short return-producing intervals, including call results returned immediately and simple arithmetic values produced directly for return.
- Kept long-lived values out of `rax`; this avoids clobbering loop-carried values in array/object fast paths that use `rax` as target scratch.
- Preserved runtime trace epilogue behavior; return values in `rax` are still saved around `rt_trace_pop`.
- Direct double expressions already flow through `xmm0`; full XMM interval coalescing remains with slice 6.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    16368    17116   +748
stack_memory_instruction_count        8417     5708  -2709
stack_load_count                      4424     2429  -1995
stack_store_count                     3720     2974   -746
register_copy_count                    284     3914  +3630
callee_saved_save_count                  0      366   +366
callee_saved_restore_count               0      366   +366
```

Compared with slice 4, total instructions improved from `17159` to `17116`, register copies improved from `3953` to `3914`, and callee-saved save/restore counts improved from `368` each to `366` each.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py -q
```

## Slice 6: Allocate XMM Registers For `double` Intervals

### Goal

Allocate physical XMM registers for `double` virtual registers instead of spilling all XMM intervals to stack.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/locations.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_locations.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py`

### What To Do

1. Add an XMM allocation pool.
2. Allocate call-free double intervals to caller-saved XMM registers.
3. Keep stack fallback for unsupported or high-pressure XMM intervals.
4. Update frame layout so XMM physical locations do not receive ordinary stack slots unless needed.
5. Ensure physical XMM names flow through target locations and debug comments.

### Checklist

- [x] Add XMM allocation pool usage.
- [x] Allocate call-free double intervals.
- [x] Preserve stack fallback for spilled doubles.
- [x] Avoid unnecessary double stack homes.
- [x] Add allocator tests for XMM assignment and spills.
- [x] Add double emission tests.
- [x] Measure double-heavy samples.

### Implementation Notes

- Added a conservative call-free XMM allocation pool, `xmm2` through `xmm14`, leaving `xmm0`, `xmm1`, and `xmm15` available for the current double lowering and call-lowering scratch conventions.
- Allocated only double intervals that do not cross modeled calls or safepoints and do not overlap fixed XMM ABI constraints in the chosen pool.
- Kept stack fallback for high-pressure or unsupported XMM intervals.
- Updated floating load/store helpers and allocated entry loads so physical XMM locations are used directly when present, while spilled doubles still use frame slots.
- Left ABI XMM argument/result coalescing to slice 7.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/std/math/test_math.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    21766    23801  +2035
stack_memory_instruction_count       12938     9457  -3481
stack_load_count                      5641     2686  -2955
stack_store_count                     5098     4596   -502
register_copy_count                    247     5829  +5582
callee_saved_save_count                  0      233   +233
callee_saved_restore_count               0      233   +233
```

This slice substantially reduces stack traffic in a double-heavy sample, while the remaining increase in total instructions is still dominated by register-copy traffic and callee-saved save/restore overhead.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py -q
./scripts/golden.sh --filter 'std/math/**'
```

## Slice 7: Make Double Lowering XMM-Location Aware

### Goal

Teach double instruction selection and call lowering to use allocated XMM locations directly.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/cast_codegen.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`
- `compiler/backend/targets/x86_64_sysv/abi.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_backend_parity.py`

### What To Do

1. Load double operands directly from allocated XMM registers when present.
2. Write double arithmetic and comparison results directly to allocated XMM/GPR locations where legal.
3. Coalesce double arguments into `xmm0` through `xmm7`.
4. Coalesce double call results and returns with `xmm0`.
5. Keep double-to-int and int-to-double casts correct around fixed runtime helpers.

### Checklist

- [x] Use allocated XMM locations for double loads.
- [x] Use allocated XMM destinations for double arithmetic.
- [x] Reduce double call argument moves.
- [x] Reduce double return and call-result moves.
- [x] Preserve checked double cast behavior.
- [x] Add focused double assembly and execution tests.
- [x] Measure `std/math` and double-heavy cases.

### Implementation Notes

- Double loads already consult allocated XMM locations; this slice made the arithmetic and unary lowering choose an allocated XMM destination directly when available.
- Added a conservative double argument preference pool for ABI XMM argument registers `xmm2` through `xmm7`. The current lowering still reserves `xmm0`, `xmm1`, and `xmm15` as hardwired scratch/return registers.
- Extended call-argument reload metadata to cover XMM argument registers, using `movq` spills and forced stack reloads around trace/root hooks just like the GPR argument path.
- Added `xmm0` as a return-only allocation preference for short double return intervals and immediate double call-result returns.
- Kept checked double cast behavior on the existing scratch-register path; no cast lowering broadening was needed for this slice.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/std/math/test_math.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    21766    23731  +1965
stack_memory_instruction_count       12938     9335  -3603
stack_load_count                      5641     2686  -2955
stack_store_count                     5098     4596   -502
register_copy_count                    247     5829  +5582
callee_saved_save_count                  0      233   +233
callee_saved_restore_count               0      233   +233
```

Compared with slice 6, total instructions improved from `23801` to `23731`, and stack-memory instructions improved from `9457` to `9335`.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_doubles.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_backend_parity.py -q
./scripts/golden.sh --filter 'std/math/**'
```

## Slice 8: Add Global Copy Coalescing

### Goal

Move beyond dead-at-copy coalescing by coalescing virtual registers globally when their live ranges do not interfere and their physical constraints are compatible.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/analysis/liveness.py`

Possible new file:

- `compiler/backend/targets/x86_64_sysv/coalescing.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`

### What To Do

1. Build a copy graph from `BackendCopyInst`, call argument preferences, and return preferences.
2. Add interference checks using intervals and instruction-level liveness.
3. Union non-interfering copy-related virtual registers into allocation groups.
4. Merge ABI/fixed-register preferences only when compatible.
5. Keep group ordering deterministic.
6. Avoid coalescing GC references in ways that break root slot identity or safepoint synchronization.

### Checklist

- [x] Build copy graph.
- [x] Add interval and liveness interference checks.
- [x] Add allocation groups.
- [x] Merge compatible physical-register preferences.
- [x] Preserve GC root correctness.
- [x] Add positive and negative coalescing tests.
- [x] Measure register-copy count.

### Implementation Notes

- Added allocator-local copy coalescing groups built from deterministic `BackendCopyInst` edges.
- Coalescing only accepts same-class intervals, rejects GC references, rejects strict live-range interference, and checks instruction-level liveness at the copy.
- Allocation now consults coalescing groups when choosing copy, call-argument, and return-register preferences, so compatible ABI preferences can propagate through copy chains.
- Fixed-register constraints must be compatible across a group; copies that would merge different ABI homes are left uncoalesced.
- Kept this as local machinery in `register_allocation.py`; a separate `coalescing.py` can still be introduced once interval splitting makes the model larger.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    16368    17102   +734
stack_memory_instruction_count        8417     5673  -2744
stack_load_count                      4424     2429  -1995
stack_store_count                     3720     2974   -746
register_copy_count                    284     3914  +3630
callee_saved_save_count                  0      366   +366
callee_saved_restore_count               0      366   +366
```

Compared with the last recorded AoC measurement from slice 5, total instructions improved from `17116` to `17102`, and stack-memory instructions improved from `5708` to `5673`. The broad sample's register-copy count did not move yet; this slice primarily unlocks preference propagation through copy groups, while the larger remaining copy count still needs broader interval splitting and later copy-removal work.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

## Slice 9: Add Broad Interval Splitting

### Goal

Split long intervals so high-pressure regions and ABI boundaries do not force an entire value into one expensive location.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/lower_calls.py`

Possible new files:

- `compiler/backend/targets/x86_64_sysv/interval_splitting.py`
- `compiler/backend/targets/x86_64_sysv/resolution_moves.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py`

### What To Do

1. Introduce allocation fragments for one virtual register.
2. Split around:
   - calls
   - safepoints
   - loop boundaries when pressure is high
   - fixed-register operations such as division and shifts
3. Insert resolution moves at fragment boundaries.
4. Keep resolution moves block-local unless CFG edge moves are explicitly modeled.
5. Preserve deterministic block-order-sensitive placement.

### Checklist

- [x] Add interval fragment model.
- [x] Split around calls and fixed-register operations.
- [x] Split high-pressure straight-line regions.
- [x] Add resolution move emission.
- [x] Preserve CFG correctness and deterministic placement.
- [x] Add tests for loops, branches, and calls.
- [x] Measure spill and copy tradeoffs.

### Implementation Notes

- Added `X86_64SysVAllocationFragment` and `X86_64SysVResolutionMove` metadata to the allocation result.
- Single-call-crossing non-GC GPR intervals may now use caller-saved registers after callee-saved registers in the pool, which means caller-saved choices are used as pressure relief rather than the first choice for call-crossing values.
- Multi-call-crossing intervals remain in callee-saved registers for now; broad CFG-aware resolution is needed before they can safely use repeated caller-saved split points.
- Existing caller-saved spill/reload emission is now represented as explicit resolution moves, and allocation fragments record stack boundary fragments at call split points.
- Fragment boundaries are also recorded at fixed-register constraints and ordered block entry points, giving later CFG edge-resolution work deterministic places to attach moves.
- GC references remain excluded from caller-saved split allocation, preserving root slot identity and safepoint synchronization.

### Measurement Notes

Measured with:

```text
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

```text
metric                          without_ra  with_ra  delta
------------------------------  ----------  -------  -----
instruction_count                    16368    17017   +649
stack_memory_instruction_count        8417     5680  -2737
stack_load_count                      4424     2440  -1984
stack_store_count                     3720     2966   -754
register_copy_count                    284     3826  +3542
callee_saved_save_count                  0      367   +367
callee_saved_restore_count               0      367   +367
```

Compared with slice 8, total instructions improved from `17102` to `17017`, register-copy count improved from `3914` to `3826`, and stack-memory instructions are roughly flat at `5680`.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_control_flow.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
./scripts/golden.sh --filter 'aoc/**'
```

## Slice 10: Add Rematerialization For Cheap Values

### Goal

Avoid spilling and reloading values that are cheaper to recreate than to store.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/register_allocation.py`
- `compiler/backend/targets/x86_64_sysv/instruction_selection.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`

Possible new file:

- `compiler/backend/targets/x86_64_sysv/rematerialization.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_strings.py`

### What To Do

1. Identify rematerializable values:
   - small integer constants
   - null constants
   - function references loaded with `lea`
   - selected static addresses when safe
2. Prefer rematerialization over stack spill/reload under pressure.
3. Keep non-cheap constants and GC-sensitive references conservative.
4. Add stats for rematerialized values if useful.

### Checklist

- [ ] Add rematerializable-value metadata.
- [ ] Prefer rematerialization under pressure.
- [ ] Emit rematerialization at use sites.
- [ ] Preserve function-reference and null behavior.
- [ ] Add tests for constants and callable values.
- [ ] Measure stack-load reductions.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_strings.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_calls.py -q
```

## Slice 11: Reduce Stack Homes And Callee-Saved Save/Restore Cost

### Goal

Once caller-saved allocation, XMM allocation, and splitting are stable, remove remaining unnecessary stack homes and callee-saved saves/restores.

### Where

Existing files:

- `compiler/backend/targets/x86_64_sysv/frame.py`
- `compiler/backend/targets/x86_64_sysv/emit.py`
- `compiler/backend/targets/x86_64_sysv/root_codegen.py`
- `compiler/backend/targets/x86_64_sysv/register_allocation.py`

Tests:

- `tests/compiler/backend/targets/x86_64_sysv/test_emit_basics.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py`
- `tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py`

### What To Do

1. Allocate stack homes only for:
   - spilled values
   - values needing root slots or debug-preserved homes
   - values needing call-save slots
   - values needed by fallback code paths
2. Avoid callee-saved prologue saves when the register is used only in call-free fragments.
3. Consider late shrinking of callee-saved sets after splitting.
4. Keep root slots separate from ordinary stack homes where it improves clarity.

### Checklist

- [ ] Narrow stack-home allocation.
- [ ] Keep root slots correct for physical and stack values.
- [ ] Shrink callee-saved save/restore sets after splitting.
- [ ] Add frame-layout tests.
- [ ] Add root-runtime execution tests.
- [ ] Measure stack-memory and callee-saved counts.

### How To Test

```text
pytest tests/compiler/backend/targets/x86_64_sysv/test_emit_runtime_roots.py -q
pytest tests/compiler/backend/targets/x86_64_sysv/test_register_allocation.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

## Slice 12: Improve Measurement, Regression Gates, And Diagnostics

### Goal

Make performance harvest visible and protect it from regressions.

### Where

Existing files:

- `scripts/assembly_stats.py`
- `docs/X86_64_SYSV_REGISTER_ALLOCATION_PLAN.md`
- `docs/X86_64_SYSV_REGISTER_ALLOCATION_BROADENING_PLAN.md`
- target/debug-comment code under `compiler/backend/targets/x86_64_sysv`

Possible new files:

- `tests/compiler/test_assembly_stats_regressions.py`
- `docs/X86_64_SYSV_REGISTER_ALLOCATION_MEASUREMENTS.md`

Tests:

- `tests/compiler/test_assembly_stats_script.py`
- selected golden specs

### What To Do

1. Add measurement scenarios:
   - arithmetic-heavy
   - call-heavy
   - double-heavy
   - GC/root-heavy
   - AoC solver sample
2. Track:
   - instruction count
   - stack memory instructions
   - register copies
   - callee-saved saves/restores
   - caller-saved save/reloads around calls
   - XMM stack spills/reloads
3. Add optional allocation diagnostics in debug comments:
   - physical location
   - allocation fragment
   - spill reason
   - coalescing group
4. Document final before/after numbers.

### Checklist

- [ ] Add representative measurement set.
- [ ] Extend assembly stats for caller-saved and XMM-specific metrics.
- [ ] Add allocation diagnostics where helpful.
- [ ] Add regression tests for stats parsing.
- [ ] Record final broadening measurements.
- [ ] Decide whether the all-stack fallback remains useful.

### How To Test

```text
pytest tests/compiler/test_assembly_stats_script.py -q
pytest tests/compiler/backend/targets/x86_64_sysv -q
./scripts/golden.sh --filter 'arithmetic/**'
./scripts/golden.sh --filter 'std/math/**'
./scripts/golden.sh --filter 'aoc/**'
/bin/python3 scripts/assembly_stats.py tests/golden/aoc/2025/10/part2/test_solver.nif --omit-runtime-trace
```

## Done Criteria

This broadening phase is complete when:

1. Caller-saved GPR allocation is enabled by default.
2. XMM register allocation is enabled by default for double values.
3. Interval splitting exists for calls, fixed-register operations, and high-pressure regions.
4. Global coalescing handles ordinary copies, call arguments, and returns without breaking ABI constraints.
5. Representative samples show lower total instruction counts with register allocation than without it.
6. GC root tests, integration tests, and relevant golden tests pass with allocation enabled.
7. The all-stack fallback is either removed or documented as a deliberate internal diagnostic switch.
