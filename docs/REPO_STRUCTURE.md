# Repository Structure

This document summarizes the current repository layout for MVP v0.1 work.

## Top-Level Files

- [README.md](../README.md) - project overview and policy highlights.
- `pyproject.toml` - Python tooling/test configuration.

## `compiler/`

Stage-0 compiler implementation in Python.

- `frontend/` - syntax-layer package.
	- `tokens.py` - token kinds and lexer token tables.
	- `lexer.py` - lexical analysis with source spans, token objects, and diagnostics.
	- `ast_nodes.py` - canonical AST dataclasses.
	- `parser.py` - recursive-descent parser for modules/statements/expressions.
	- `ast_dump.py` - deterministic AST debug serialization used by golden tests.
- `resolver.py` - module graph loading and import/export visibility resolution.
- `semantic/` - typed semantic IR and post-lowering semantic passes.
	- `ir.py` - source-oriented semantic IR node definitions.
	- `lowered_ir.py` - lowered semantic IR used after executable-oriented lowering.
	- `symbols.py` - canonical semantic symbol identities, including owner-scoped `LocalId`.
	- `types.py`, `type_compat.py` - canonical semantic type references and compatibility helpers.
	- `display.py` - semantic display-name helpers for locals, members, and call targets.
	- `operations.py` - shared semantic operator and dispatch helpers.
	- `lowering/` - semantic IR construction from resolved, typechecked source.
		- `orchestration.py` - explicit lowering entry point and phase composition.
		- `resolution.py` - shared resolver/context helpers used across lowering modules.
		- `calls.py`, `collections.py`, `expressions.py`, `references.py`, `statements.py`, `type_refs.py`, `ids.py`, `locals.py`, `literals.py`, `executable.py` - lowering helpers split by concern.
	- `linker.py` - semantic-program ordering and duplicate-symbol consolidation.
	- `optimizations/` - post-lowering semantic passes and transforms.
		- `pipeline.py` - semantic optimization pass sequencing entry point.
		- `unreachable_prune.py` - semantic reachability analysis and unreachable declaration pruning.
		- `constant_fold.py`, `copy_propagation.py`, `dead_stmt_prune.py`, `dead_store_elimination.py`, `redundant_cast_elimination.py`, `simplify_control_flow.py` - current semantic optimization passes.
- `typecheck/` - typecheck package modules.
	- `api.py` - typecheck entry points (`typecheck`, `typecheck_program`).
	- `model.py` - shared typechecker data model/constants/errors.
	- `context.py`, `constants.py` - explicit checker context/state helpers and extracted constants.
	- `relations.py` - extracted type relation helpers.
	- `module_lookup.py`, `type_resolution.py` - extracted lookup and type resolution helpers.
	- `declarations.py` - extracted declaration pre-pass and field-initializer validation helpers.
	- `calls.py` - extracted call typing and call-argument validation helpers.
	- `structural.py` - extracted indexing, slicing, and iteration protocol helpers.
	- `expressions.py` - extracted non-call expression inference and field-assignability helpers.
	- `statements.py` - extracted statement checking, return analysis, assignment-target validation, and visibility helpers.
	- `engine.py` - lean internal typecheck engine adapter composed from the extracted helper modules.
- `codegen/` - backend package entry point and internal code generation modules.
	- `generator.py` - shared backend state and emission coordination.
	- `model.py`, `metadata.py`, `class_hierarchy.py`, `layout.py`, `measurement.py`, `root_liveness.py`, `root_slot_plan.py`, `runtime_calls.py`, `strings.py`, `symbols.py`, `types.py`, `walk.py` - backend metadata, layout, liveness, runtime-call, and symbol helpers.
	- `asm.py`, `ops_int.py`, `ops_float.py` - assembly building and operator instruction selection.
	- `emitter_expr.py`, `emitter_stmt.py`, `emitter_fn.py`, `emitter_module.py` - layered expression, statement, function, and module emission.
	- `abi/` - backend ABI and array-lowering helpers used by codegen.
- `cli.py` - minimal phase-oriented CLI scaffold.
- `main.py` - package entry point.
- `grammar/niflheim_v0_1.ebnf` - canonical grammar source.

## `runtime/`

Current C runtime and GC support for the generated backend.

- `include/runtime.h` - runtime ABI declarations.
- `include/array.h` - fixed-size array runtime API declarations.
- `include/gc.h`, `include/gc_trace.h`, `include/gc_tracked_set.h` - GC and tracing support headers.
- `include/io.h` - runtime file/stdout byte-array API declarations.
- `include/panic.h`, `include/runtime_dbg.h` - panic and debug/test helper declarations.
- `src/runtime.c` - low-level runtime infrastructure (thread state, root frames, allocation, panic support).
- `src/gc.c` - GC implementation unit.
- `src/gc_trace.c` - trace-frame bookkeeping and summary reporting.
- `src/gc_tracked_set.c` - tracked-allocation set utilities.
- `src/io.c` - runtime file/stdout byte-array implementation unit.
- `src/array.c` - fixed-size array allocation/access/slice implementation.
- `src/panic.c` - panic reporting and trace rendering.
- `src/runtime_dbg.c` - debug/test-only helper implementations.
- `Makefile` - runtime static library build.

## `std/`

Standard library modules layered on the compiler/runtime surface.

- `io.nif` - stdout printing, whole-file reads, stdin reads, and argv decoding helpers.
- `str.nif`, `vec.nif`, `map.nif`, `box.nif`, `lang.nif` - core containers, boxing, and shared interface definitions.
- `object.nif`, `range.nif`, `error.nif`, `test.nif`, `bigint.nif` - supporting standard-library modules.

## `tests/`

Current active suites:

- `compiler/` - compiler unit and integration coverage across frontend, resolver, typecheck, semantic, codegen, and CLI behavior.
- `runtime/` - runtime-focused tests and supporting fixtures.
- `golden/` - snapshot-style outputs used by selected end-to-end checks.

## `samples/`

Small `.nif` source programs used for language bring-up, runtime checks, and experimentation.

## `scripts/`

Utility scripts for repository workflows (for example golden refresh/build helpers).

## `docs/`

Supporting documentation:

- [REPO_STRUCTURE.md](REPO_STRUCTURE.md) - this file.
- [GRAMMAR_EBNF.md](GRAMMAR_EBNF.md) - grammar conventions and parser-facing notes.
- [LANGUAGE_MVP_SPEC_V0.1.md](LANGUAGE_MVP_SPEC_V0.1.md) - canonical language and implementation checklist.
- [SEMANTIC_IR_SPEC.md](SEMANTIC_IR_SPEC.md) - current semantic IR node set, invariants, and layering boundaries.
- [ROADMAP_v0.1.md](ROADMAP_v0.1.md) - milestone ordering plus current completion-status summary.
- [INTERFACES_V1.md](INTERFACES_V1.md) - implemented interface design and runtime-dispatch model.
- [ABI_NOTES.md](ABI_NOTES.md) - compiler/runtime ABI notes.
- [RUNTIME_CODEGEN_HOT_PATH_PLAN.md](RUNTIME_CODEGEN_HOT_PATH_PLAN.md) - staged implementation plan for shadow-stack, root-slot, allocation, and tracked-set hot paths.
- [TEST_PLAN_v0.1.md](TEST_PLAN_v0.1.md) - testing strategy and release gate criteria.
- [SUGARING_DESIGN.md](SUGARING_DESIGN.md) - canonical sugar protocols (indexing/slicing and for-in iteration).
- [TRACI_HIGH_VALUE_ADDITIONS_PLAN.md](TRACI_HIGH_VALUE_ADDITIONS_PLAN.md) - staged plan for math, file-output, RNG, and primitive-buffer additions needed before a practical Traci port.
- `archive/` - implemented plans and superseded design notes retained for historical context.
- [archive/CODEGEN_ROOT_SLOT_LIVENESS_PLAN.md](archive/CODEGEN_ROOT_SLOT_LIVENESS_PLAN.md) - implemented plan for precise root-slot liveness and reduced runtime-call scaffolding in codegen.
- [archive/EXPLICIT_CONSTRUCTORS_PLAN.md](archive/EXPLICIT_CONSTRUCTORS_PLAN.md) - implemented plan for explicit constructors and constructor-only overload resolution as preparation for inheritance.
- [archive/FLOW_SENSITIVE_TYPE_NARROWING_PLAN.md](archive/FLOW_SENSITIVE_TYPE_NARROWING_PLAN.md) - implemented plan for eliminating redundant runtime type checks using branch-local type facts.
- [archive/OVERRIDE_VIRTUAL_DISPATCH_PLAN.md](archive/OVERRIDE_VIRTUAL_DISPATCH_PLAN.md) - implemented plan for explicit `override` plus virtual class dispatch after single inheritance.
- [archive/PROPER_MODULE_SEMANTICS_PLAN.md](archive/PROPER_MODULE_SEMANTICS_PLAN.md) - implemented plan for canonical top-level module identity, qualification, and codegen naming.
- [archive/SINGLE_INHERITANCE_PLAN.md](archive/SINGLE_INHERITANCE_PLAN.md) - implemented plan for single inheritance as a subtype/layout feature that prepares later override and virtual dispatch work.
- [archive/VM_BENCHMARK_PLAN.md](archive/VM_BENCHMARK_PLAN.md) - implemented plan for the VM benchmark regression workload.
